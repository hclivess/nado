// pets-art/polar.js — BESPOKE hand-drawn SVG art for POLAR & ARCTIC animals (NADO Pets).
// Each value: (c) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,62), within
// x,y ∈ [8,112]. Colours come from the coat object c (c.body / c.shade / c.line); the palette is applied at
// runtime, so real colours are NOT hardcoded (horns/antlers/bills may use fixed warm tones + #fff/INK).
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/ears/fins/wings <g class="tail-wag">.
// Aquatic (beluga/seaotter/harpseal) set float:true in the roster and are oriented horizontally, head RIGHT.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// fixed warm accents that stay constant across coats
const HORN = "#d9b98a";  // horns / antlers / boss
const HOOF = "#5b5048";  // dark cloven hooves
const WHT  = "#fbf6ee";  // pale muzzle blaze / plume highlight (a highlight, not coat)
const BILL = "#f2a03b";  // bird bill / feet
const REDB = "#e0564d";  // tern red bill / ptarmigan comb
const LEGY = "#f2c94c";  // egret yellow legs

// thin cloven deer/caribou legs (vertical, hooves at the bottom)
const deerlegs = (c, xs, y = 90, h = 20) => xs.map((x) =>
  `<path d="M${x} ${y} l0 ${h}" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M${x} ${y} l0 ${h}" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/><path d="M${x} ${y + h} l-2.6 3 M${x} ${y + h} l2.6 3" stroke="${HOOF}" stroke-width="2.4" stroke-linecap="round"/>`).join("");
// thin scaly bird legs with three splayed toes
const birdlegs = (xs, y = 88, h = 12, col = BILL) => xs.map((x) =>
  `<path d="M${x} ${y} l0 ${h} M${x} ${y + h} l-4 4 M${x} ${y + h} l4 4 M${x} ${y + h} l0 5" stroke="${col}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");

export const ART_POLAR = {
  // ── Polar Bear — heavy build, small round ears on a long neck, elongated snout, black nose (tier 3)
  polarbear: (c) => `
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="31" ry="23" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="93" rx="17" ry="11" fill="${c.shade}" opacity=".55"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 76 : 44}" cy="103" rx="11" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M${i ? 71 : 39} 104 q6 4 12 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".45"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="47" cy="33" r="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="47" cy="33" r="3.2" fill="${c.shade}"/>
      ${mirror(`<circle cx="47" cy="33" r="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="47" cy="33" r="3.2" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="46" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M50 52 Q50 74 60 74 Q70 74 70 52 Q60 47 50 52 Z" fill="${c.shade}" opacity=".55"/>
      <ellipse cx="60" cy="60" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="60" rx="4.6" ry="3.4" fill="${INK}"/>
      <path d="M60 63 v5 M60 68 q-4 3 -7 1 M60 68 q4 3 7 1" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eyes(52, 68, 44, 2.6, eyeInk(c))}
    </g>`,

  // ── Musk Ox — massive shaggy skirt of fur, hooked horns off a central boss, low broad head (tier 3)
  muskox: (c) => `
    <g class="breathe">
      <path d="M28 64 Q30 46 60 44 Q90 46 92 64 Q94 92 86 98 L82 84 L76 98 L70 85 L64 98 L58 85 L52 98 L46 84 L42 98 Q26 92 28 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 78 h40 M44 88 h32" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="58" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${(() => { const h = `<path d="M46 47 Q32 50 31 65 Q31 76 42 73 Q37 63 47 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`; return h + mirror(h); })()}
      <path d="M45 46 Q60 40 75 46 Q76 55 60 55 Q44 55 45 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="10" ry="8" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="4.2" ry="3" fill="${INK}"/>
      <path d="M56 66 h-5 M64 66 h5" stroke="${INK}" stroke-width="1.2" opacity=".5"/>
      ${eyes(51, 69, 54, 2.4, eyeInk(c))}
    </g>`,

  // ── Caribou — profile, huge sweeping branched antlers + forward brow shovel, neck mane (tier 2)
  caribou: (c) => `
    <g class="breathe">
      <ellipse cx="52" cy="80" rx="27" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M30 84 q22 9 44 0" fill="${c.shade}" opacity=".45"/>
      ${deerlegs(c, [36, 48, 62, 72], 90, 20)}
    </g>
    <g class="head-tilt">
      <path d="M66 74 Q70 54 80 46 Q88 44 90 52 Q84 60 80 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M70 72 Q74 56 82 50" stroke="${c.shade}" stroke-width="4" fill="none" opacity=".5" stroke-linecap="round"/>
      <path d="M80 44 Q98 40 102 50 Q102 58 92 58 Q82 56 80 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="99" cy="53" rx="3" ry="2.4" fill="${INK}"/>
      <path d="M84 41 Q80 43 82 47" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${eye(87, 47, 2.6, eyeInk(c))}
      ${tube("M82 42 Q78 22 62 16 Q54 14 50 18", HORN, c.line, 4)}
      ${tube("M70 22 Q66 14 58 12 M62 16 Q58 10 66 8", HORN, c.line, 3.2)}
      ${tube("M84 40 Q86 24 96 18 Q102 16 104 22", HORN, c.line, 4)}
      ${tube("M92 22 Q94 12 102 12", HORN, c.line, 3.2)}
      ${tube("M83 44 Q74 40 70 32", HORN, c.line, 3)}
    </g>`,

  // ── Reindeer — front-facing, symmetric branching antlers, oval ears, big dark nose, compact (tier 2)
  reindeer: (c) => {
    const ant = tube("M52 40 Q46 24 34 20 M48 30 Q40 26 34 30 M50 34 Q44 34 40 40", HORN, c.line, 3.4);
    const ear = `<ellipse cx="45" cy="50" rx="6" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2" transform="rotate(-20 45 50)"/>`;
    return `
    <g class="breathe">
      <ellipse cx="60" cy="82" rx="23" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="88" rx="12" ry="8" fill="${c.shade}" opacity=".5"/>
      ${deerlegs(c, [46, 56, 64, 74], 90, 18)}
    </g>
    <g class="head-tilt">
      ${ant}${mirror(ant)}
      ${ear}${mirror(ear)}
      <ellipse cx="60" cy="56" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 60 Q50 76 60 76 Q70 76 70 60 Q60 55 50 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="68" rx="5.5" ry="4.5" fill="${INK}"/>
      ${eyes(52, 68, 54, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Wolverine — low stocky mustelid, bushy tail, pale side-blaze, dark mask, small fierce face (tier 3)
  wolverine: (c) => `
    <g class="tail-wag"><path d="M28 82 Q10 78 10 92 Q18 96 28 92 Q34 88 34 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M14 88 q8 3 16 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/></g>
    <g class="breathe">
      <path d="M30 84 Q30 62 58 60 Q90 60 90 84 Q86 100 58 100 Q34 100 30 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M34 76 Q60 66 86 76" stroke="${c.shade}" stroke-width="7" fill="none" stroke-linecap="round" opacity=".85"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 74 : 38}" y="92" width="9" height="14" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M64 46 L60 34 L72 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M64 46 L60 34 L72 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="56" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M46 54 Q60 46 74 54 Q74 48 60 46 Q46 48 46 54 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M52 60 Q52 76 60 76 Q68 76 68 60 Q60 56 52 60 Z" fill="${INK}" opacity=".85"/>
      <ellipse cx="60" cy="63" rx="4" ry="3" fill="${INK}"/>
      <path d="M56 72 l4 3 l4 -3" stroke="#fff" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(52, 68, 54, 2.6, eyeInk(c))}
    </g>`,

  // ── Ermine — slender upright weasel, tiny rounded ears, whiskers, long black-tipped tail (tier 2)
  ermine: (c) => `
    <g class="tail-wag"><path d="M42 88 Q26 96 22 82 Q20 72 30 74 Q38 78 44 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M22 82 Q18 76 22 72 Q28 72 28 78 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="breathe">
      <path d="M48 96 Q42 66 52 46 Q60 40 68 46 Q76 66 70 96 Q60 102 48 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 90 Q60 70 60 52" stroke="${c.shade}" stroke-width="6" fill="none" opacity=".4" stroke-linecap="round"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 66 : 54}" cy="96" rx="4.5" ry="3" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="52" cy="34" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>${mirror(`<circle cx="52" cy="34" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <ellipse cx="60" cy="42" rx="13" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 46 Q60 54 66 46 Q60 44 54 46 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="47" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M60 49 v3 M53 47 h-7 M53 49 h-6 M67 47 h7 M67 49 h6" stroke="${INK}" stroke-width="1" opacity=".5"/>
      ${eyes(53, 67, 40, 2.4, eyeInk(c))}
    </g>`,

  // ── Snow Fox — curled & fluffy: short rounded ears, bushy tail wrapped round tucked paws (tier 2)
  snowfox: (c) => `
    <g class="tail-wag"><path d="M30 96 Q8 92 12 70 Q18 58 30 62 Q22 74 30 84 Q40 80 48 88 Q42 98 30 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M16 74 Q14 86 24 90" stroke="${c.shade}" stroke-width="4" fill="none" opacity=".4" stroke-linecap="round"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="82" rx="27" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="62" cy="92" rx="16" ry="10" fill="${c.shade}" opacity=".5"/>
      <ellipse cx="52" cy="98" rx="8" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="head-tilt">
      <path d="M48 40 Q42 26 52 24 Q60 28 58 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M50 30 Q47 27 54 28 L54 36 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M48 40 Q42 26 52 24 Q60 28 58 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M50 30 Q47 27 54 28 L54 36 Z" fill="${c.shade}"/>`)}
      ${pom(62, 56, 20, c.body, c.line, 13, 2.4)}
      <path d="M52 56 Q62 76 72 56 Q68 66 62 66 Q56 66 52 56 Z" fill="${c.shade}"/>
      <path d="M62 66 l-7 5 M62 66 l7 5" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="62" cy="64" rx="2.6" ry="2" fill="${INK}"/>
      ${eyes(53, 71, 54, 2.6, eyeInk(c))}
    </g>`,

  // ── Husky — sitting sled dog, sharp erect ears, spectacle mask, pale muzzle, tight curled tail (tier 2)
  husky: (c) => `
    <g class="tail-wag"><path d="M84 88 Q104 84 100 66 Q94 56 86 62 Q92 72 84 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M90 64 Q96 72 90 80" stroke="${c.shade}" stroke-width="4" fill="none" opacity=".5" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M38 98 Q34 66 60 64 Q86 66 82 98 Q60 106 38 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 96 Q50 74 60 70 Q70 74 70 96 Q60 100 50 96 Z" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 70 : 50}" cy="100" rx="8" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M42 44 L38 22 L56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M44 40 L42 28 L52 38 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M42 44 L38 22 L56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M44 40 L42 28 L52 38 Z" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="54" rx="20" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M52 44 Q56 58 52 70 Q60 66 60 54 Q60 66 68 70 Q64 58 68 44 Z" fill="${c.shade}" opacity=".8"/>
      <path d="M54 62 Q54 76 60 76 Q66 76 66 62 Q60 58 54 62 Z" fill="${WHT}"/>
      <ellipse cx="60" cy="63" rx="3.6" ry="2.8" fill="${INK}"/>
      <path d="M60 66 v4 M60 70 q-4 2 -7 0 M60 70 q4 2 7 0" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(52, 68, 52, 2.8, eyeInk(c))}
    </g>`,

  // ── Malamute — bigger, fluffier: rounded ears, heavy pom ruff, cap-mask, thick plume tail (tier 2)
  malamute: (c) => `
    <g class="tail-wag"><path d="M82 96 Q106 96 104 74 Q98 62 88 68 Q96 80 82 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 70 Q98 80 90 88" stroke="${c.shade}" stroke-width="5" fill="none" opacity=".5" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M34 100 Q30 64 60 62 Q90 64 86 100 Q60 108 34 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 98 Q46 72 60 68 Q74 72 74 98 Q60 104 46 98 Z" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 72 : 48}" cy="102" rx="9" ry="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M40 42 Q36 24 52 30 L54 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M44 38 Q42 30 50 33 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M40 42 Q36 24 52 30 L54 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M44 38 Q42 30 50 33 Z" fill="${c.shade}"/>`)}
      ${pom(60, 60, 24, c.body, c.line, 14, 2.4)}
      <path d="M46 50 Q54 62 50 74 Q60 68 60 56 Q60 68 70 74 Q66 62 74 50 Q60 44 46 50 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M52 64 Q52 78 60 78 Q68 78 68 64 Q60 60 52 64 Z" fill="${WHT}"/>
      <ellipse cx="60" cy="65" rx="4" ry="3" fill="${INK}"/>
      <path d="M60 68 v4 M60 72 q-4 2 -8 0 M60 72 q4 2 8 0" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(52, 68, 54, 2.8, eyeInk(c))}
    </g>`,

  // ── Arctic Hare — compact, SHORT black-tipped ears, very round fluffy body, tucked feet (tier 2)
  arctichare: (c) => `
    <g class="tail-wag"><circle cx="40" cy="92" r="7" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="82" rx="26" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="92" rx="15" ry="10" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 76 : 44}" cy="102" rx="10" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M49 42 Q45 29 54 27 Q61 30 59 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M51 31 Q49 28 55 29 L56 35 Z" fill="${INK}"/>
      ${mirror(`<path d="M49 42 Q45 29 54 27 Q61 30 59 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M51 31 Q49 28 55 29 L56 35 Z" fill="${INK}"/>`)}
      <ellipse cx="60" cy="54" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 58 Q60 64 65 58 Q60 56 55 58 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="58" rx="2.4" ry="1.8" fill="${INK}"/>
      <path d="M60 60 v3 M54 59 h-7 M66 59 h7" stroke="${INK}" stroke-width="1" opacity=".45"/>
      ${eyes(52, 68, 51, 2.6, eyeInk(c))}
    </g>`,

  // ── Snowshoe Hare — leaner, LONG ears, oversized "snowshoe" hind foot, alert (tier 1)
  snowshoehare: (c) => `
    <g class="tail-wag"><circle cx="38" cy="88" r="6" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="80" rx="22" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="62" cy="88" rx="12" ry="9" fill="${c.shade}" opacity=".5"/>
      <path d="M34 99 Q26 93 34 84 Q58 82 63 97 Q52 105 34 99 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 96 h18" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/>
      <ellipse cx="76" cy="100" rx="8" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="head-tilt">
      <path d="M52 38 Q49 8 58 6 Q65 10 61 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M55 12 Q53 8 60 9 L59 22 Z" fill="${INK}"/>
      ${mirror(`<path d="M52 38 Q49 8 58 6 Q65 10 61 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M55 12 Q53 8 60 9 L59 22 Z" fill="${INK}"/>`)}
      <ellipse cx="62" cy="52" rx="16" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M57 56 Q62 62 67 56 Q62 54 57 56 Z" fill="${c.shade}"/>
      <ellipse cx="62" cy="56" rx="2.2" ry="1.7" fill="${INK}"/>
      <path d="M62 58 v3 M56 57 h-7 M68 57 h7" stroke="${INK}" stroke-width="1" opacity=".45"/>
      ${eyes(54, 70, 49, 2.5, eyeInk(c))}
    </g>`,

  // ── Lemming — tiny round plump rodent, near-hidden ears, stubby tail, low to the ground (tier 1)
  lemming: (c) => `
    <g class="tail-wag"><path d="M34 82 q-6 2 -4 6" stroke="${c.line}" stroke-width="3" fill="none" stroke-linecap="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="78" rx="28" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="86" rx="16" ry="10" fill="${c.shade}" opacity=".5"/>
      <path d="M46 62 Q60 54 74 62" stroke="${c.shade}" stroke-width="5" fill="none" opacity=".4" stroke-linecap="round"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 70 : 50}" cy="98" rx="6" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="50" cy="52" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>${mirror(`<circle cx="50" cy="52" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <ellipse cx="60" cy="60" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="64" rx="8" ry="6" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="60" cy="63" rx="2.4" ry="1.8" fill="${INK}"/>
      <path d="M60 65 v2 M55 64 h-6 M65 64 h6" stroke="${INK}" stroke-width="0.9" opacity=".45"/>
      ${eyes(53, 67, 57, 2.3, eyeInk(c))}
    </g>`,

  // ── Harp Seal — floating pup: huge round eyes, chubby body, harp saddle, fore-flipper (tier 2, float)
  harpseal: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M22 62 Q10 52 8 62 Q10 72 22 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="66" rx="34" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M40 52 Q62 42 84 52 Q80 62 62 62 Q44 62 40 52 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M46 78 Q40 90 52 90 Q56 84 54 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 80 l3 6 M52 80 l2 6" stroke="${c.line}" stroke-width="1" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="84" cy="62" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="96" cy="64" rx="4" ry="3" fill="${INK}"/>
      <path d="M96 67 Q92 70 88 68" stroke="${INK}" stroke-width="1.3" fill="none"/>
      <path d="M92 62 h-8 M92 66 h-7" stroke="${INK}" stroke-width="0.9" opacity=".5"/>
      <g class="blink"><circle cx="82" cy="60" r="4.6" fill="${E}"/><circle cx="83.7" cy="58.3" r="1.5" fill="#fff"/>
        <circle cx="72" cy="62" r="4.6" fill="${E}"/><circle cx="73.7" cy="60.3" r="1.5" fill="#fff"/></g>
    </g>`;
  },

  // ── Ringed Seal — hauled out on ice: upright, ring-spot coat, whiskered face, fore-flippers (tier 2)
  ringedseal: (c) => `
    <g class="tail-wag"><path d="M56 100 Q60 110 64 100 Q60 96 56 100 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="breathe">
      <path d="M40 100 Q34 70 60 56 Q86 70 80 100 Q60 108 40 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[[48, 78], [68, 80], [56, 90], [72, 92], [44, 90]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".8"/>`).join("")}
      ${["", "s"].map((_, i) => `<path d="M${i ? 70 : 44} 92 Q${i ? 82 : 32} 96 ${i ? 76 : 38} 104 Q${i ? 70 : 44} 102 ${i ? 70 : 44} 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="46" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="54" rx="9" ry="7" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="60" cy="52" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M60 55 Q56 58 53 56 M60 55 Q64 58 67 56" stroke="${INK}" stroke-width="1.2" fill="none"/>
      <path d="M53 52 h-8 M53 55 h-7 M67 52 h8 M67 55 h7" stroke="${INK}" stroke-width="0.9" opacity=".5"/>
      ${eyes(52, 68, 44, 2.8, eyeInk(c))}
    </g>`,

  // ── Beluga — smooth white whale: bulbous melon forehead, gentle smile, NO dorsal fin (tier 3, float)
  beluga: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M20 62 Q8 50 6 60 Q10 62 8 64 Q6 74 20 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q34 44 66 42 Q92 42 100 54 Q104 60 100 66 Q92 82 66 82 Q34 80 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 70 Q64 78 90 70" stroke="${c.shade}" stroke-width="3" fill="none" opacity=".4" stroke-linecap="round"/>
      <path d="M54 76 Q48 90 60 88 Q62 82 60 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 50 Q84 46 90 50" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".5" stroke-linecap="round"/>
      <path d="M92 62 Q100 64 99 68 Q95 68 92 66" fill="${c.shade}" opacity=".5"/>
      <path d="M91 64 Q96 67 101 63" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eye(86, 58, 2.8, E)}
    </g>`;
  },

  // ── Sea Otter — floating on its back, paws clasped on chest, whiskered upturned face (tier 2, float)
  seaotter: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M94 74 Q112 74 108 86 Q100 86 92 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="72" rx="38" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="56" cy="74" rx="26" ry="11" fill="${c.shade}" opacity=".5"/>
      <path d="M64 66 Q60 56 66 52 Q72 56 70 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M72 66 Q68 56 74 52 Q80 56 78 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${["", "s"].map((_, i) => `<ellipse cx="22" cy="${i ? 62 : 82}" rx="6" ry="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <ellipse cx="88" cy="52" rx="15" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="80" cy="41" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="96" cy="41" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="88" cy="56" rx="8" ry="7" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="88" cy="53" rx="3" ry="2.4" fill="${INK}"/>
      <path d="M88 56 Q84 59 81 57 M88 56 Q92 59 95 57" stroke="${INK}" stroke-width="1.2" fill="none"/>
      <path d="M81 53 h-7 M81 56 h-6 M95 53 h7 M95 56 h6" stroke="${INK}" stroke-width="0.9" opacity=".5"/>
      ${eyes(82, 94, 49, 2.6, E)}
    </g>`;
  },

  // ── Ptarmigan — plump ground grouse, red eye-comb, short bill, feathered feet (tier 1)
  ptarmigan: (c) => `
    <g class="tail-wag"><path d="M32 78 Q18 82 20 70 Q28 72 36 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="76" rx="26" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M50 74 Q62 82 76 74 Q80 84 62 92 Q46 86 50 74 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M52 88 Q56 84 58 90 M64 90 Q68 86 70 92" stroke="${c.shade}" stroke-width="6" fill="none" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="66" cy="48" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M78 46 Q86 46 84 52 Q80 52 78 50 Z" fill="${BILL}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 38 Q66 34 72 38 Q68 42 60 40 Z" fill="${REDB}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(70, 47, 2.8, eyeInk(c))}
    </g>`,

  // ── Snowy Egret — tall wader, long S-neck, black dagger bill, yellow feet, wispy plumes (tier 2)
  snowyegret: (c) => `
    <g class="breathe">
      ${birdlegs([54, 66], 84, 24, LEGY)}
      <path d="M42 84 Q40 58 60 56 Q80 58 78 84 Q60 94 42 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 70 Q42 82 40 74 M50 74 Q46 86 44 78" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".5"/>
    </g>
    <g class="tail-wag"><path d="M40 76 Q26 82 30 70 Q36 74 42 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      <path d="M64 60 Q62 40 72 30 Q78 26 82 30 Q76 40 76 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="80" cy="28" rx="10" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M88 28 L104 30 L88 33 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M74 22 Q68 18 64 20" stroke="${c.shade}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eye(82, 27, 2.4, eyeInk(c))}
    </g>`,

  // ── Arctic Tern — sleek seabird, black cap, red bill, deeply forked tail, short red legs (tier 2)
  arctictern: (c) => `
    <g class="tail-wag"><path d="M30 68 L12 60 L26 68 L12 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 68 Q40 50 66 52 Q86 54 84 66 Q78 78 54 78 Q36 78 30 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 60 Q64 58 82 62 L78 70 Q60 68 46 70 Z" fill="${c.shade}" opacity=".6"/>
      ${birdlegs([58, 66], 76, 8, REDB)}
    </g>
    <g class="head-tilt">
      <circle cx="80" cy="46" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M70 40 Q80 30 92 42 Q86 46 80 44 Q74 44 70 40 Z" fill="${INK}"/>
      <path d="M90 46 L106 48 L90 52 Z" fill="${REDB}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(82, 46, 2.4, "#e9edf2")}
    </g>`,

  // ── Snow Bunting — chunky little songbird, conical bill, dark wing patch, perched (tier 1)
  snowbunting: (c) => `
    <g class="tail-wag"><path d="M34 76 L18 80 L32 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="66" rx="24" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M44 60 Q56 66 74 60 Q78 74 58 82 Q42 76 44 60 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M50 66 Q58 70 68 66 M50 72 Q58 76 66 72" stroke="${c.line}" stroke-width="1" opacity=".35" fill="none"/>
      ${birdlegs([52, 64], 86, 10, BILL)}
    </g>
    <g class="head-tilt">
      <circle cx="66" cy="44" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 36 Q66 32 72 36 Q70 42 66 42 Q62 42 60 36 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M78 42 L90 46 L78 50 Z" fill="${BILL}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(69, 43, 2.6, eyeInk(c))}
    </g>`,
};

// roster metadata — merged into the master roster; every `n` slugifies to an ART_POLAR key
export const ROSTER_POLAR = [
  { n: "Polar Bear",    e: "🐻‍❄️", tier: 3, float: false },
  { n: "Musk Ox",       e: "🐂",   tier: 3, float: false },
  { n: "Caribou",       e: "🦌",   tier: 2, float: false },
  { n: "Reindeer",      e: "🦌",   tier: 2, float: false },
  { n: "Wolverine",     e: "🦡",   tier: 3, float: false },
  { n: "Ermine",        e: "🐾",   tier: 2, float: false },
  { n: "Snow Fox",      e: "🦊",   tier: 2, float: false },
  { n: "Husky",         e: "🐕",   tier: 2, float: false },
  { n: "Malamute",      e: "🐕",   tier: 2, float: false },
  { n: "Arctic Hare",   e: "🐇",   tier: 2, float: false },
  { n: "Snowshoe Hare", e: "🐇",   tier: 1, float: false },
  { n: "Lemming",       e: "🐹",   tier: 1, float: false },
  { n: "Harp Seal",     e: "🦭",   tier: 2, float: true  },
  { n: "Ringed Seal",   e: "🦭",   tier: 2, float: false },
  { n: "Beluga",        e: "🐋",   tier: 3, float: true  },
  { n: "Sea Otter",     e: "🦦",   tier: 2, float: true  },
  { n: "Ptarmigan",     e: "🐦",   tier: 1, float: false },
  { n: "Snowy Egret",   e: "🐦",   tier: 2, float: false },
  { n: "Arctic Tern",   e: "🐦",   tier: 2, float: false },
  { n: "Snow Bunting",  e: "🐦",   tier: 1, float: false },
];
