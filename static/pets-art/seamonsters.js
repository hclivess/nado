// pets-art/seamonsters.js — BESPOKE hand-drawn SVG art for the SEAMONSTERS batch (mythic aquatic
// creatures) of the NADO Pets roster. Each entry: slug -> (c) => "<svg inner markup>" for
// <svg viewBox="0 0 120 120">. Coat: c.body (main fill), c.shade (accent/underside), c.line (outline).
// ALL float:true => oriented HORIZONTALLY, head to the RIGHT (like the sea/reef batches). Continuous
// silhouette + 2-tone shading (belly()/tint()/deepen()) + tucked fins/tentacles. Helpers from ../pets-draw.js.
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile, eyeInk } from "../pets-draw.js";

const GLOW = "#eafff4"; // magic / spray / dish-water / glowing eyes
const TOOTH = "#fff";   // teeth / fangs
const HORN = "#f2c94c"; // horns / hooks / beak / hat straw
const MOON = "#f2e6c8"; // Bakunawa's swallowed moon
const TIP = "#e0564d";  // forked tongue tip

export const ART_SEAMONSTERS = {
  // ── Leviathan — colossal whale-beast: blunt spouting head, spined dorsal ridge, fanged jaw, plated belly (t6)
  leviathan: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M26 62 Q10 46 4 50 Q13 62 4 78 Q12 74 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M6 52 Q-1 62 6 72" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="breathe">
      ${[38, 50, 62, 74].map((x) => `<path d="M${x} 44 l4 -10 l4 10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
      <path d="M24 62 Q30 42 60 42 Q92 42 104 58 Q106 62 104 66 Q92 84 60 84 Q30 84 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 74 Q68 88 100 66 Q68 82 40 74 Z" fill="${B}"/>
      <path d="M46 78 h30 M50 82 h22" stroke="${c.line}" stroke-width="1" opacity=".45"/>
      <path d="M54 78 Q52 92 66 86 Q58 82 54 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M96 44 q-3 -10 -7 -13 M96 44 q3 -10 8 -12 M96 44 q0 -11 1 -16" fill="none" stroke="${GLOW}" stroke-width="2" stroke-linecap="round" opacity=".8"/>
      <path d="M84 68 Q98 78 106 66 Q98 74 90 73 Q86 71 84 68 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${88 + i * 3.4} 69 l1.4 4 l1.5 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${eye(96, 56, 3, E)}
    </g>`; },

  // ── Sea Serpent — long undulating serpent, dorsal spike crest, fanged head + forked tongue (t4)
  seaserpent: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      ${tube("M14 54 Q8 62 14 72", c.body, c.line, 6)}
      <path d="M13 54 l-6 -4 l2 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M14 64 Q32 48 50 62 Q68 74 82 60", c.body, c.line, 15)}
      <path d="M20 64 Q34 54 50 62 Q66 70 78 60" fill="none" stroke="${B}" stroke-width="5" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      ${[[24, 55], [40, 53], [56, 59]].map(([x, y]) => `<path d="M${x} ${y} l3 -9 l3 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M72 56 Q92 48 100 60 Q100 72 84 74 Q70 70 72 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M70 52 l2 -9 l5 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <path d="M82 66 Q94 72 100 63" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M86 66 l1.3 3.6 l1.4 -3.6 Z M92 66 l1.3 3.6 l1.4 -3.6 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>
      <path d="M100 64 q8 1 12 -2 M108 63 l4 -2 M108 64 l4 2" stroke="${TIP}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eye(86, 57, 2.8, E)}
    </g>`; },

  // ── Merfolk — human torso + scaled fish tail (swimming right), flowing hair, twin-lobe flukes (t3)
  merfolk: (c) => { const B = belly(c), SKIN = tint(c.body, 0.55); return `
    <g class="tail-wag">
      <path d="M28 62 Q14 46 6 50 Q14 60 8 62 Q14 64 6 74 Q14 78 28 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M28 62 Q40 50 60 52 Q74 54 78 64 Q74 72 60 72 Q40 74 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[40, 50, 60].map((x) => `<path d="M${x} 56 q4 4 0 8" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>`).join("")}
      <path d="M34 66 Q54 74 76 64 Q54 70 34 66 Z" fill="${B}" opacity=".7"/>
      <path d="M70 58 Q78 52 84 56 Q86 62 82 66 Q74 66 70 60 Z" fill="${SKIN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M78 58 Q74 66 68 68" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M78 58 Q74 66 68 68" fill="none" stroke="${SKIN}" stroke-width="2.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 44 Q70 46 74 60 Q80 52 88 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="90" cy="46" r="10" fill="${SKIN}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M80 44 Q82 32 92 33 Q100 34 100 44 Q94 38 88 39 Q82 40 80 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(92, 46, 2.6, INK)}
      ${smile(94, 49, 2.2, INK)}
    </g>`; },

  // ── Siren — winged sea-singer: swept feather wing tucked behind, open singing mouth, drifting note (t4)
  siren: (c) => { const B = belly(c), SKIN = tint(c.body, 0.55); return `
    <g class="tail-wag">
      <path d="M56 56 Q34 34 12 30 Q26 44 28 54 Q18 50 10 54 Q26 62 40 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 56 Q34 42 20 38 M48 58 Q34 50 22 50" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>
    </g>
    <g class="breathe">
      <path d="M34 66 Q30 82 44 84 Q40 74 46 70 Q40 68 34 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 60 Q46 46 62 44 Q78 44 80 60 Q76 76 60 76 Q46 74 46 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 66 Q62 74 74 66 Q62 70 52 66 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      <path d="M78 40 Q66 44 70 58 Q76 50 84 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="86" cy="44" r="10" fill="${SKIN}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 42 Q78 30 88 31 Q97 32 97 43 Q90 36 84 37 Q78 38 76 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(88, 43, 2.6, INK)}
      <ellipse cx="91" cy="49" rx="2" ry="2.6" fill="${INK}"/>
      <g stroke="${c.line}" stroke-width="0.8"><circle cx="102" cy="41" r="2.6" fill="${GLOW}"/><path d="M104.4 41 v-9 l4 2 v6" fill="${GLOW}"/></g>
    </g>`; },

  // ── Selkie — seal-person: sleek seal body, soulful near-front face, swept hair, pearl necklace (t3)
  selkie: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag"><path d="M26 66 Q12 60 6 54 Q14 66 6 78 Q14 74 26 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 66 Q32 48 58 48 Q82 48 92 58 Q98 62 96 70 Q90 82 58 82 Q32 82 24 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 76 Q64 86 92 70 Q64 82 40 76 Z" fill="${B}"/>
      <path d="M52 78 Q56 90 66 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${[76, 80, 84, 88].map((x, i) => `<circle cx="${x}" cy="${66 + i * 0.4}" r="1.5" fill="${GLOW}" stroke="${c.line}" stroke-width="0.6"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="86" cy="58" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M74 52 Q76 40 88 40 Q98 41 99 52 Q92 45 84 46 Q77 47 74 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 54 Q66 56 64 64 Q72 60 78 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="92" cy="62" rx="5" ry="4" fill="${B}"/>
      <ellipse cx="94" cy="61" rx="1.6" ry="1.3" fill="${INK}"/>
      ${eyes(82, 90, 56, 3, E)}
      <path d="M88 66 q3 2 6 0" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>`; },

  // ── Kappa — turtle-imp: domed shell, beaked imp face, the signature water-dish crown, webbed hand (t3)
  kappa: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M34 72 Q22 78 20 88 Q30 82 40 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 60 Q30 42 54 42 Q72 42 72 60 Q72 74 50 74 Q30 74 30 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 48 L52 46 L60 54 L54 66 L42 64 Z" fill="${c.body}" opacity=".5" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M58 58 Q58 46 74 46 Q88 46 90 60 Q88 74 72 74 Q58 72 58 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <ellipse cx="74" cy="62" rx="10" ry="8" fill="${B}"/>
      <path d="M62 72 Q58 82 66 84 Q66 78 68 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="88" cy="52" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <ellipse cx="88" cy="42" rx="8" ry="3.2" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="88" cy="41.5" rx="5" ry="1.8" fill="${tint(GLOW, 0.3)}"/>
      <path d="M96 52 Q104 50 104 55 Q104 60 96 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M96 55 h8" stroke="${c.line}" stroke-width="1" opacity=".6"/>
      ${eyes(84, 92, 50, 2.6, E)}
    </g>`; },

  // ── Rusalka — pale water-spirit: translucent body dissolving into curls, streaming hair, a single tear (t3)
  // Rusalka — the melancholic Slavic water-maiden, after Bilibin: long streaming hair as the centrepiece,
  // pale reclining figure, a curling fish tail below, bold contours, a water-lily tucked in her hair.
  rusalka: (c) => { const SKIN = tint(c.body, 0.62), HAIR = c.body, TAIL = c.shade, B = belly(c); return `
    <g class="breathe">
      <path d="M46 24 Q28 30 24 50 Q20 68 29 82 Q34 92 43 93 Q40 80 40 65 Q40 49 49 39 Q52 31 46 24 Z" fill="${HAIR}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M66 24 Q84 30 88 50 Q92 68 83 82 Q78 92 69 93 Q72 80 72 65 Q72 49 63 39 Q60 31 66 24 Z" fill="${HAIR}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M31 58 Q34 44 44 34 M83 58 Q80 44 70 34 M28 76 Q31 60 39 50 M86 76 Q83 60 75 50" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".38" stroke-linecap="round"/>
      <path d="M50 62 Q44 76 51 86 Q44 90 39 98 Q53 96 57 87 Q61 96 71 97 Q64 88 62 81 Q67 72 60 62 Z" fill="${TAIL}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 71 Q56 75 60 71 M50 79 Q56 83 61 79" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".5"/>
      <path d="M49 38 Q56 33 63 38 Q67 47 64 58 Q61 68 56 71 Q50 68 48 58 Q45 47 49 38 Z" fill="${SKIN}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M53 46 Q56 51 60 46 Q56 50 53 46 Z" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M45 26 Q50 13 61 14 Q73 15 75 28 Q68 19 60 20 Q51 20 45 26 Z" fill="${HAIR}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 27 Q41 38 47 49 Q49 39 52 33 Z" fill="${HAIR}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 27 Q71 38 65 49 Q63 39 60 33 Z" fill="${HAIR}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="56" cy="30" r="11" fill="${SKIN}" stroke="${c.line}" stroke-width="2.5"/>
      <g transform="translate(68,20)">${[18,90,162,234,306].map((a)=>`<circle cx="${(Math.cos(a*Math.PI/180)*3).toFixed(1)}" cy="${(Math.sin(a*Math.PI/180)*3).toFixed(1)}" r="2" fill="#f3d0e0" stroke="${c.line}" stroke-width="0.7"/>`).join("")}<circle r="1.6" fill="#f2cf4e"/></g>
      ${eyes(52, 60, 30, 2.4, INK)}
      ${smile(56, 35, 2, INK)}
    </g>`; },

  // ── Cetus — whale-monster: stout body, spined back, curled fin, long fanged snout gaping maw (t4)
  cetus: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M28 62 Q12 44 6 48 Q14 58 8 62 Q14 66 6 76 Q12 80 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${[40, 52, 64].map((x) => `<path d="M${x} 46 l4 -9 l4 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>`).join("")}
      <path d="M26 62 Q30 44 56 44 Q80 44 92 56 Q80 80 56 80 Q30 80 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.7" stroke-linejoin="round"/>
      <path d="M38 72 Q62 84 88 66 Q62 80 38 72 Z" fill="${B}"/>
      <path d="M50 76 Q46 90 60 86 Q52 82 50 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 50 Q98 46 108 54 Q112 58 108 62 L96 62 Q98 66 92 68 Q80 72 76 60 Q76 52 78 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 60 Q104 58 108 55 Q108 62 104 65 Q96 68 92 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${Array.from({ length: 4 }, (_, i) => `<path d="M${94 + i * 3.4} 59 l1.3 3.4 l1.4 -3.4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      <path d="M80 50 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(84, 53, 3, E)}
    </g>`; },

  // ── Bakunawa — moon-eating dragon-eel: undulating body, dorsal frill, whiskers, jaws lunging at the moon (t5)
  bakunawa: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      ${tube("M12 58 Q6 64 12 70", c.body, c.line, 6)}
      <path d="M14 56 l-6 -3 l2 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M12 64 Q30 50 48 64 Q64 76 78 62", c.body, c.line, 14)}
      <path d="M18 64 Q34 54 48 64 Q62 72 76 62" fill="none" stroke="${B}" stroke-width="5" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      ${[[26, 54], [40, 52], [54, 60]].map(([x, y]) => `<path d="M${x} ${y} q3 -8 7 -2 q-2 2 -3 4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="105" cy="36" r="10" fill="${MOON}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="108" cy="31" r="1.6" fill="${c.line}" opacity=".25"/><circle cx="110" cy="39" r="1.2" fill="${c.line}" opacity=".25"/><circle cx="103" cy="30" r="1.1" fill="${c.line}" opacity=".25"/>
      <path d="M72 60 Q78 46 92 46 Q104 46 104 56 L96 58 Q102 60 100 66 Q92 72 80 70 Q70 68 72 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 50 Q104 50 104 55 L96 57 Q94 53 92 50 Z" fill="${INK}"/>
      ${Array.from({ length: 3 }, (_, i) => `<path d="M${94 + i * 3} 53 l1.2 3 l1.3 -3 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      <path d="M78 48 Q74 38 68 36 M81 47 Q79 38 75 34" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M74 66 q-8 2 -12 -1 M76 68 q-8 4 -13 3" fill="none" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".7"/>
      ${eye(84, 56, 2.8, E)}
    </g>`; },

  // ── Makara — croc-fish: scaled fish body + fins, long toothy crocodile snout, ridged brow (t4)
  makara: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M28 62 Q12 46 6 50 Q15 62 6 74 Q12 78 28 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M26 62 Q34 46 58 46 Q78 46 84 58 Q78 74 58 76 Q34 78 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 72 Q58 82 82 66 Q58 78 38 72 Z" fill="${B}"/>
      ${[40, 50, 60].map((x) => `<path d="M${x} 54 q5 6 0 12" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>`).join("")}
      <path d="M48 48 Q56 38 66 48 Q56 50 50 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M54 74 Q56 84 66 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 54 Q88 50 96 52 L112 50 Q114 54 112 56 L96 58 Q98 62 94 66 Q82 70 76 62 Q76 56 78 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M96 53 L110 51" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <ellipse cx="109" cy="52.5" rx="1.4" ry="1" fill="${INK}"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${90 + i * 3.5} 58 l1 3 l1.2 -3 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      <path d="M80 53 q5 -3 9 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 55, 2.8, E)}
    </g>`; },

  // ── Nessie — plesiosaur: rounded humped body, paddle flipper, long S-neck rising to a small snouted head (t4)
  nessie: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">${tube("M28 68 Q16 70 10 64", c.body, c.line, 7)}</g>
    <g class="breathe">
      <path d="M24 68 Q26 54 44 54 Q56 54 62 62 Q70 54 82 56 Q92 58 92 68 Q88 80 58 80 Q28 80 24 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M34 74 Q58 84 88 70 Q58 80 34 74 Z" fill="${B}"/>
      <path d="M46 74 Q44 88 58 84 Q50 80 46 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${tube("M80 64 Q92 46 96 30", c.body, c.line, 11)}
      <ellipse cx="99" cy="27" rx="11" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M104 22 l2 -5 M96 20 l0 -5" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>
      ${eye(102, 25, 2.6, E)}
      ${smile(105, 29, 2, E)}
    </g>`; },

  // ── Charybdis — whirlpool maw: spiralling vortex disc, ring of fangs around a black gullet, water arms (t5)
  charybdis: (c) => {
    const swirl = Array.from({ length: 30 }, (_, i) => { const a = i / 30 * Math.PI * 3.2; const r = 8 + i * 1.6; return `${(60 + r * Math.cos(a)).toFixed(1)} ${(62 + r * Math.sin(a)).toFixed(1)}`; }).join(" L");
    const arms = [0, 1, 2, 3, 4].map((k) => { const a = (-90 + k * 72) * Math.PI / 180; const x = 60 + 41 * Math.cos(a), y = 62 + 41 * Math.sin(a); return tube(`M${(60 + 24 * Math.cos(a)).toFixed(1)} ${(62 + 24 * Math.sin(a)).toFixed(1)} Q${(60 + 34 * Math.cos(a + 0.4)).toFixed(1)} ${(62 + 34 * Math.sin(a + 0.4)).toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`, c.body, c.line, 5); }).join("");
    const fangs = Array.from({ length: 12 }, (_, i) => { const a = i / 12 * 2 * Math.PI; const x1 = 60 + 14 * Math.cos(a), y1 = 62 + 14 * Math.sin(a); const x2 = 60 + 9 * Math.cos(a), y2 = 62 + 9 * Math.sin(a); const nx = 60 + 11.5 * Math.cos(a + 0.14), ny = 62 + 11.5 * Math.sin(a + 0.14); return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${nx.toFixed(1)} ${ny.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)} Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`; }).join("");
    return `
    <g class="tail-wag">${arms}</g>
    <g class="breathe">
      <circle cx="60" cy="62" r="34" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M${swirl}" fill="none" stroke="${c.shade}" stroke-width="2.4" opacity=".6" stroke-linecap="round"/>
      <circle cx="60" cy="62" r="14" fill="${INK}" stroke="${c.line}" stroke-width="2"/>
      ${fangs}
    </g>
    <g class="head-tilt">
      ${eyes(51, 69, 49, 3, "#e9edf2")}
    </g>`; },

  // ── Scylla — many-headed sea beast: central hub, three rearing sea-hound heads, tentacle base (t5)
  scylla: (c) => { const E = eyeInk(c), B = belly(c);
    const hound = (x, y) => `
      <path d="M${x} ${y} Q${x + 12} ${y - 6} ${x + 16} ${y + 2} Q${x + 18} ${y + 8} ${x + 10} ${y + 9} Q${x} ${y + 8} ${x} ${y} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M${x + 2} ${y - 3} l-2 -6 l6 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M${x + 9} ${y + 6} q5 2 8 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M${x + 11} ${y + 5} l1 3 l1.2 -3 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>
      ${eye(x + 11, y + 1, 2.2, E)}`;
    return `
    <g class="tail-wag">
      ${[40, 54, 68, 80].map((x, i) => tube(`M${x} 76 Q${x - 6 + i * 2} 92 ${x + (i % 2 ? 6 : -6)} 104`, c.body, c.line, 5)).join("")}
    </g>
    <g class="breathe">
      <path d="M40 72 Q40 56 60 56 Q80 56 82 72 Q78 84 60 84 Q42 84 40 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M48 76 Q60 84 74 76 Q60 80 48 76 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      ${tube("M46 62 Q36 52 30 46", c.body, c.line, 6)} ${hound(28, 42)}
      ${tube("M52 60 Q50 44 58 36", c.body, c.line, 6)} ${hound(56, 30)}
      ${tube("M64 60 Q70 46 80 42", c.body, c.line, 6)} ${hound(78, 38)}
    </g>`; },

  // ── Umibozu — dark shadow spirit: huge smooth shadow silhouette, big glowing eyes, unsettling grin (t4)
  umibozu: (c) => { const D = deepen(c.body, 0.5); return `
    <g class="tail-wag">
      <path d="M30 92 Q40 82 52 88 Q60 82 68 88 Q80 82 90 92 Q60 100 30 92 Z" fill="${D}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M28 60 Q28 24 60 24 Q92 24 92 60 Q92 88 60 90 Q28 88 28 60 Z" fill="${D}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M42 40 Q54 30 66 34 Q54 38 48 48 Z" fill="#fff" opacity=".12"/>
    </g>
    <g class="head-tilt">
      <g class="blink">
        <circle cx="49" cy="54" r="7" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/>
        <circle cx="71" cy="54" r="7" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/>
        <circle cx="49" cy="55" r="3" fill="${INK}"/><circle cx="71" cy="55" r="3" fill="${INK}"/>
      </g>
      <path d="M46 70 Q60 82 74 70 Q60 76 46 70 Z" fill="${INK}" opacity=".85"/>
    </g>`; },

  // ── Ningyo — fish-mermaid: fish body + fins, an eerie little human face patch with fringe & hands (t3)
  ningyo: (c) => { const B = belly(c), SKIN = tint(c.body, 0.5); return `
    <g class="tail-wag">
      <path d="M28 62 Q12 48 6 52 Q15 62 6 72 Q12 76 28 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M26 62 Q34 46 60 46 Q82 46 90 60 Q82 76 60 76 Q34 78 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 72 Q60 82 86 66 Q60 78 38 72 Z" fill="${B}"/>
      <path d="M46 48 Q54 40 62 48 Q54 50 50 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M56 74 Q54 84 64 80 Q58 78 56 74 Z" fill="${SKIN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="80" cy="60" rx="11" ry="12" fill="${SKIN}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M70 54 Q72 46 82 46 Q90 47 90 55 Q84 50 78 51 Q72 52 70 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(76, 84, 58, 2.6, INK)}
      ${smile(80, 62, 2, INK)}
    </g>`; },

  // ── Isonade — hooked shark-beast: shark torpedo, tall dorsal, gold barbed hooks on tail & fins, toothy grin (t4)
  isonade: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M30 62 L10 42 Q18 62 10 82 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M12 46 q-4 -2 -4 -6 M14 78 q-4 2 -4 6" fill="none" stroke="${HORN}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M28 62 Q40 46 68 46 Q92 48 102 60 Q94 74 68 78 Q40 78 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 70 Q66 82 96 66 Q66 78 40 70 Z" fill="${B}"/>
      <path d="M54 48 L62 26 L72 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M62 26 q6 0 7 6" fill="none" stroke="${HORN}" stroke-width="2" stroke-linecap="round"/>
      <path d="M52 76 L58 90 L68 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M58 90 q4 2 4 6" fill="none" stroke="${HORN}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M76 52 q-2 8 0 16 M81 52 q-2 8 0 16" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M80 66 Q94 78 104 62 Q96 72 86 71 Q82 69 80 66 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${84 + i * 3.4} 67 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${eye(90, 56, 2.8, E)}
    </g>`; },

  // ── Hafgufa — island-whale: vast low body so huge an island of rock & a lone tree sits on its back (t5)
  hafgufa: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M20 66 Q8 54 3 50 Q11 66 3 82 Q9 78 20 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M16 66 Q28 52 70 52 Q104 52 114 66 Q106 78 70 82 Q28 82 16 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 74 Q72 84 106 70 Q72 80 40 74 Z" fill="${B}"/>
      <path d="M38 54 Q44 38 58 40 Q74 40 78 54 Q58 58 38 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="48" cy="49" rx="4" ry="2.6" fill="${deepen(c.shade, 0.2)}"/><ellipse cx="68" cy="50" rx="3.4" ry="2.2" fill="${deepen(c.shade, 0.2)}"/>
      <path d="M60 42 v-8" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M60 22 l7 12 h-14 Z" fill="${tint(c.body, 0.15)}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M60 28 l5 8 h-10 Z" fill="${tint(c.body, 0.15)}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M104 52 q-2 -8 -6 -10 M104 52 q2 -8 6 -9" fill="none" stroke="${GLOW}" stroke-width="1.8" stroke-linecap="round" opacity=".8"/>
      <path d="M100 70 q7 3 12 -2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(104, 63, 2.6, E)}
    </g>`; },

  // ── Lusca — half-octopus half-shark: shark front + dorsal, back half trailing suckered tentacles (t4)
  lusca: (c) => { const B = belly(c), E = eyeInk(c);
    const arms = ["M34 60 Q16 56 8 64", "M36 66 Q18 70 10 82", "M38 62 Q22 62 14 72", "M34 70 Q20 84 24 96"];
    return `
    <g class="tail-wag">
      ${arms.map((d) => tube(d, c.body, c.line, 6)).join("")}
      ${arms.map((d) => { const m = d.match(/(\d+) (\d+)$/); return `<circle cx="${+m[1]}" cy="${+m[2]}" r="1.6" fill="${c.shade}"/>`; }).join("")}
    </g>
    <g class="breathe">
      <path d="M34 62 Q44 46 70 46 Q92 48 102 60 Q94 74 70 78 Q44 78 34 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 70 Q70 82 98 66 Q70 78 46 70 Z" fill="${B}"/>
      <path d="M56 48 L64 28 L74 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 76 L62 88 L72 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 52 q-2 8 0 16 M83 52 q-2 8 0 16" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M80 66 Q94 78 104 62 Q96 72 86 71 Q82 69 80 66 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${84 + i * 3.4} 67 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${eye(90, 56, 2.8, E)}
    </g>`; },

  // ── Encantado — dolphin-shifter: graceful dolphin with a jaunty straw hat (hiding the blowhole) & a sparkle (t3)
  encantado: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag"><path d="M26 64 Q12 56 6 50 Q16 63 6 78 Q14 71 28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 66 Q32 48 58 47 Q78 47 90 55 L102 54 Q108 56 104 61 Q98 63 90 61 Q85 66 79 68 Q58 80 40 76 Q30 73 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 72 Q62 82 84 66 Q62 78 40 72 Z" fill="${B}"/>
      <path d="M56 47 Q59 30 46 33 Q54 41 52 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 72 Q56 86 71 80 Q62 76 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 44 Q92 44 96 48 Q88 50 80 49 Q80 46 84 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M76 50 q12 -4 24 0 q-12 4 -24 0 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M88 60 Q96 59 104 59" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(84, 56, 2.6, E)}
      <path d="M104 44 l1 3 l3 1 l-3 1 l-1 3 l-1 -3 l-3 -1 l3 -1 Z" fill="${GLOW}" stroke="${HORN}" stroke-width="0.6" stroke-linejoin="round"/>
    </g>`; },

  // ── Tiamat — primordial sea dragon: grand body, spined ridge, fin-wing, horned fanged head, cheek frill (t6)
  tiamat: (c) => { const B = belly(c), E = eyeInk(c); return `
    <g class="tail-wag">
      ${tube("M38 74 Q16 84 10 64 Q7 54 18 52", c.body, c.line, 9)}
      <path d="M18 52 l-8 -5 l3 8 l-8 0 l6 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M60 50 Q40 22 14 18 Q28 36 34 52 Q22 46 12 50 Q30 60 46 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M54 50 Q40 32 26 26 M52 53 Q40 44 30 44" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="breathe">
      ${[42, 52, 62, 72].map((x) => `<path d="M${x} 52 l4 -10 l4 10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>`).join("")}
      <path d="M36 66 Q36 48 64 48 Q88 48 92 66 Q88 84 64 84 Q36 84 36 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.7" stroke-linejoin="round"/>
      <path d="M46 78 Q64 89 84 78 Q64 84 46 78 Z" fill="${B}"/>
      <path d="M50 80 h28 M53 84 h20" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M84 44 Q80 26 68 22 Q76 35 78 48 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M94 44 Q93 26 82 20 Q87 34 89 48 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="92" cy="58" rx="15" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M100 52 Q114 52 112 64 Q108 70 99 66 Q96 58 100 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M100 65 l1.4 4 l1.4 -4 Z M105 65 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="108" cy="57" rx="1.4" ry="1.1" fill="${INK}"/>
      <path d="M80 62 Q72 64 70 72 Q78 68 84 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(92, 54, 3.4, E)}
    </g>`; },
};

export const ROSTER_SEAMONSTERS = [
  { n: "Leviathan",  e: "🐋", tier: 6, float: true },
  { n: "Sea Serpent", e: "🐍", tier: 4, float: true },
  { n: "Merfolk",    e: "🧜", tier: 3, float: true },
  { n: "Siren",      e: "🎶", tier: 4, float: true },
  { n: "Selkie",     e: "🦭", tier: 3, float: true },
  { n: "Kappa",      e: "🐢", tier: 3, float: true },
  { n: "Rusalka",    e: "👻", tier: 3, float: true },
  { n: "Cetus",      e: "🐳", tier: 4, float: true },
  { n: "Bakunawa",   e: "🌙", tier: 5, float: true },
  { n: "Makara",     e: "🐊", tier: 4, float: true },
  { n: "Nessie",     e: "🦕", tier: 4, float: true },
  { n: "Charybdis",  e: "🌀", tier: 5, float: true },
  { n: "Scylla",     e: "👹", tier: 5, float: true },
  { n: "Umibozu",    e: "👤", tier: 4, float: true },
  { n: "Ningyo",     e: "🐟", tier: 3, float: true },
  { n: "Isonade",    e: "🦈", tier: 4, float: true },
  { n: "Hafgufa",    e: "🏝️", tier: 5, float: true },
  { n: "Lusca",      e: "🐙", tier: 4, float: true },
  { n: "Encantado",  e: "🐬", tier: 3, float: true },
  { n: "Tiamat",     e: "🐉", tier: 6, float: true },
];
