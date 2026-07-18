// pets-art/oddballs.js — BESPOKE hand-drawn SVG art for MARSUPIALS & ODDBALL MAMMALS (NADO Pets).
// Monotremes, marsupials and the world's weirdest placentals. Each value: (c, v) => "<svg inner markup>"
// for viewBox 0 0 120 120, animal centered ~ (60,62), within x,y ∈ [8,112]. Colours come from the coat
// object c (c.body main / c.shade accent / c.line outline); the palette is applied at runtime so real
// hues are NOT hardcoded — only warm fixed tints (claws/teeth/naked-pink/tongue/stripes) stay constant.
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/spines/ears <g class="tail-wag">.
// None float (the platypus swims but is drawn seated).
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// fixed warm accents that stay constant across coats
const CLAW = "#f2c94c", TOOTH = "#ffffff", PINK = "#f2a6b4", STRIPE = "#f4efe2", TONGUE = "#e86d84";

export const ART_ODDBALLS = {
  // ── Platypus — duck-bill monotreme, flat paddle tail, webbed feet, sleek body, beady eyes (profile, seated)
  platypus: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M34 68 Q12 60 8 74 Q8 86 26 82 Q20 74 34 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M16 68 v12 M22 66 v15 M28 66 v15" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="breathe">
      <ellipse cx="58" cy="68" rx="30" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M40 76 Q58 86 78 76 Q58 82 40 76 Z" fill="${c.shade}" opacity=".65"/>
      <path d="M44 82 Q42 96 50 98 Q56 94 52 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 82 Q64 96 72 98 Q78 94 74 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M43 96 h10 M65 96 h10" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="86" cy="58" rx="14" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M92 58 Q112 54 113 65 Q112 76 92 70 Q86 64 92 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M96 65 q9 0 15 0" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <ellipse cx="101" cy="61" rx="1.3" ry="1" fill="${INK}"/><ellipse cx="107" cy="62" rx="1.3" ry="1" fill="${INK}"/>
      ${eye(82, 52, 2.8, E)}
    </g>`;
  },

  // ── Echidna — spiny monotreme, dome of quills fanning over the back, long thin down-pointing beak-snout (front)
  echidna: (c) => {
    const E = eyeInk(c);
    let spines = "";
    for (let k = 0; k <= 12; k++) {
      const a = (180 + k * 15) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
      const bx = 60 + 30 * ca, by = 80 + 30 * sa, tx = 60 + 49 * ca, ty = 80 + 49 * sa, px = -sa, py = ca;
      spines += `<path d="M${(bx - 3.4 * px).toFixed(1)} ${(by - 3.4 * py).toFixed(1)} L${tx.toFixed(1)} ${ty.toFixed(1)} L${(bx + 3.4 * px).toFixed(1)} ${(by + 3.4 * py).toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`;
    }
    return `
    <g class="tail-wag">${spines}</g>
    <g class="breathe">
      <path d="M28 84 Q28 48 60 48 Q92 48 92 84 Q60 94 28 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 90 q4 5 8 0 M72 90 q4 5 8 0" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M41 90 l-2 4 m2 -4 l0 5 m0 -5 l2 4" stroke="${CLAW}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M79 90 l-2 4 m2 -4 l0 5 m0 -5 l2 4" stroke="${CLAW}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M60 74 Q55 92 60 101 Q65 92 60 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="100" rx="2" ry="1.5" fill="${INK}"/>
      ${eyes(52, 68, 70, 2.6, E)}
    </g>`;
  },

  // ── Opossum — pointy pale muzzle, pink nose, big rounded ears, long naked prehensile tail curling back (profile)
  opossum: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M34 84 Q12 86 10 66 Q10 56 22 58", PINK, c.line, 4)}
    </g>
    <g class="breathe">
      <ellipse cx="50" cy="80" rx="27" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M34 86 Q50 94 66 86 Q50 91 34 86 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M40 92 q-2 6 3 8 M58 92 q-2 6 3 8" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M40 92 q-2 6 3 8 M58 92 q-2 6 3 8" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="70" cy="52" rx="7" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="70" cy="53" rx="3.6" ry="4.4" fill="${PINK}" opacity=".8"/>
      <ellipse cx="86" cy="54" rx="7" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="86" cy="55" rx="3.6" ry="4.4" fill="${PINK}" opacity=".8"/>
      <path d="M62 64 Q62 48 80 48 Q100 50 110 64 Q100 73 82 73 Q64 73 62 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 58 Q112 58 110 66 Q104 72 92 68 Q88 62 92 58 Z" fill="${STRIPE}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M108 62 l4 2 l-4 2 Z" fill="${PINK}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M99 66 l10 3 M99 68 l10 1" stroke="${c.line}" stroke-width="0.9" opacity=".55"/>
      ${eye(82, 58, 2.8, E)}
    </g>`;
  },

  // ── Wombat — chunky burrower, barrel body, stubby legs, big bare nose, tiny round ears, sleepy eyes (front)
  wombat: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      <path d="M30 92 Q28 60 60 58 Q92 60 90 92 Q60 103 30 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="84" rx="18" ry="13" fill="${c.shade}" opacity=".5"/>
      <rect x="38" y="90" width="14" height="13" rx="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="68" y="90" width="14" height="13" rx="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M41 100 l0 3 m4 -3 l0 3 m4 -3 l0 3 M71 100 l0 3 m4 -3 l0 3 m4 -3 l0 3" stroke="${c.line}" stroke-width="1" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="43" cy="40" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="77" cy="40" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="60" cy="52" r="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="63" rx="13" ry="10" fill="${c.shade}"/>
      <path d="M50 62 Q60 74 70 62 Q60 68 50 62 Z" fill="${INK}"/>
      <ellipse cx="60" cy="59" rx="5.5" ry="3.6" fill="${INK}"/>
      ${eyes(50, 70, 48, 3, E)}
    </g>`;
  },

  // ── Tasmanian Devil — stocky black scavenger, gaping toothy maw, big round pink-lined ears, white chest bib (front)
  tasmaniandevil: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M34 94 Q16 94 14 80", c.body, c.line, 6)}</g>
    <g class="breathe">
      <path d="M34 96 Q32 66 60 64 Q88 66 86 96 Q60 105 34 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M48 72 Q60 92 72 72 Q60 82 48 72 Z" fill="${STRIPE}"/>
      <rect x="40" y="94" width="12" height="11" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="68" y="94" width="12" height="11" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="41" cy="42" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="41" cy="43" rx="4.6" ry="4.4" fill="${PINK}" opacity=".85"/>
      <ellipse cx="79" cy="42" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="79" cy="43" rx="4.6" ry="4.4" fill="${PINK}" opacity=".85"/>
      <path d="M40 52 Q40 34 60 34 Q80 34 80 52 Q80 66 60 70 Q40 66 40 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 56 Q60 80 74 56 Q60 64 46 56 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M50 58 l2 4 l2 -4 Z M56 60 l2 4 l2 -4 Z M62 60 l2 4 l2 -4 Z M68 58 l2 4 l2 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
      <path d="M53 68 q7 5 14 0" fill="${INK}"/>
      <ellipse cx="60" cy="52" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M48 46 q5 3 9 3 M63 49 q5 0 9 -3" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(52, 68, 46, 2.8, E)}
    </g>`;
  },

  // ── Quokka — the "happiest animal", round cheeks, tiny ears, permanent beaming smile, small forepaws (front, seated)
  quokka: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M40 98 Q28 106 40 110", c.body, c.line, 5)}</g>
    <g class="breathe">
      <path d="M38 98 Q34 70 60 68 Q86 70 82 98 Q60 106 38 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="14" ry="11" fill="${c.shade}" opacity=".5"/>
      <path d="M50 84 q-3 8 2 12 M70 84 q3 8 -2 12" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M50 84 q-3 8 2 12 M70 84 q3 8 -2 12" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="46" cy="38" rx="7" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="74" cy="38" rx="7" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="60" cy="50" r="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="42" cy="54" rx="4.5" ry="3.5" fill="${PINK}" opacity=".45"/>
      <ellipse cx="78" cy="54" rx="4.5" ry="3.5" fill="${PINK}" opacity=".45"/>
      <ellipse cx="60" cy="55" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M46 60 Q60 74 74 60" fill="none" stroke="${INK}" stroke-width="2.2" stroke-linecap="round"/>
      ${eyes(51, 69, 47, 3, E)}
    </g>`;
  },

  // ── Wallaby — small kangaroo cousin, upright on haunches, long hind foot, big ears, curved balancing tail (profile)
  wallaby: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M46 90 Q26 96 16 82 Q10 74 20 70", c.body, c.line, 8)}
    </g>
    <g class="breathe">
      <path d="M44 60 Q44 42 58 42 Q72 42 72 62 Q72 82 58 88 Q46 84 44 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 62 Q58 74 64 62 Q58 70 52 62 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M48 74 q-4 8 -2 14" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M48 74 q-4 8 -2 14" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M52 86 Q46 100 30 100 Q28 96 34 94 Q46 92 50 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M62 40 Q58 20 66 12 Q74 22 72 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M64 38 Q62 24 67 17" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M74 42 Q72 24 80 16 Q88 26 84 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M64 44 Q64 30 80 30 Q94 30 94 46 Q94 58 80 60 Q66 58 64 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M88 50 Q98 50 98 58 Q94 62 86 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="94" cy="54" rx="1.4" ry="1.1" fill="${INK}"/>
      ${eye(80, 44, 2.8, E)}
    </g>`;
  },

  // ── Numbat — slender termite-eater, pointed snout, bold white transverse back-stripes, dark eye-band, bushy tail (profile)
  numbat: (c) => {
    const E = eyeInk(c);
    let stripes = "";
    for (let i = 0; i < 6; i++) { const x = 44 + i * 6.5; stripes += `<path d="M${x} 64 Q${x + 2} 76 ${x + 3} 84" fill="none" stroke="${STRIPE}" stroke-width="2.4" stroke-linecap="round"/>`; }
    return `
    <g class="tail-wag">
      <path d="M40 74 Q18 66 10 78 Q6 88 18 90 Q14 82 26 80 Q16 84 20 92 Q28 84 42 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 76 Q42 60 62 60 Q84 60 86 76 Q84 88 60 88 Q40 88 40 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${stripes}
      <path d="M48 84 q-2 8 2 10 M74 84 q2 8 -2 10" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M48 84 q-2 8 2 10 M74 84 q2 8 -2 10" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 44 Q76 34 82 32 Q86 40 84 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 62 Q78 46 92 46 Q104 46 110 58 Q104 66 92 66 Q80 66 78 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M100 56 q9 0 10 2 Q104 62 100 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="108" cy="58" rx="1.2" ry="1" fill="${INK}"/>
      <path d="M84 50 l10 4" stroke="${c.shade}" stroke-width="4" stroke-linecap="round" opacity=".8"/>
      ${eye(90, 54, 2.6, E)}
    </g>`;
  },

  // ── Bilby — rabbit-eared bandicoot, enormous upright ears, long tapered snout, black-and-white crested tail (profile)
  bilby: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M40 82 Q20 88 14 74", INK, c.line, 5)}
      <path d="M22 84 Q10 88 8 78 Q14 76 20 78 Q12 80 16 86 Z" fill="${STRIPE}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 78 Q42 60 62 60 Q84 60 86 76 Q84 88 60 88 Q40 88 40 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 82 q-2 9 3 11 M72 82 q2 9 -3 11" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M46 82 q-2 9 3 11 M72 82 q2 9 -3 11" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M74 42 Q66 16 74 10 Q84 20 82 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M76 40 Q72 22 76 14" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M84 44 Q80 20 90 14 Q98 24 92 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 42 Q84 24 89 18" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M70 60 Q70 46 84 46 Q98 46 108 60 Q100 66 86 66 Q72 66 70 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M104 58 l6 2 l-6 2 Z" fill="${PINK}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M96 64 l10 3" stroke="${c.line}" stroke-width="0.9" opacity=".55"/>
      ${eye(82, 56, 2.8, E)}
    </g>`;
  },

  // ── Bandicoot — pointy digging snout, rounded ears, compact hunched body, stout foreclaws, short tail (profile)
  bandicoot: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M36 82 Q22 88 16 82", c.body, c.line, 5)}</g>
    <g class="breathe">
      <path d="M34 78 Q34 58 60 58 Q88 58 88 76 Q86 90 58 90 Q34 90 34 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 84 Q60 92 76 84 Q60 89 42 84 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M70 84 q0 8 4 12 M80 82 q2 8 5 11" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M70 84 q0 8 4 12 M80 82 q2 8 5 11" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 46 Q74 36 80 34 Q85 42 82 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M72 62 Q72 46 88 46 Q100 46 110 62 Q102 68 88 68 Q74 68 72 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M104 60 l6 2 l-6 2 Z" fill="${INK}"/>
      <path d="M96 65 l11 3" stroke="${c.line}" stroke-width="0.9" opacity=".55"/>
      <path d="M46 88 l-2 5 m2 -5 l1 6 m-1 -6 l3 5" stroke="${CLAW}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(88, 56, 2.8, E)}
    </g>`;
  },

  // ── Aardvark — "earth pig", arched hunched back, long tubular donkey ears, piggy snout with nostrils, digging claws (profile)
  aardvark: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M30 82 Q12 84 12 68", c.body, c.line, 7)}</g>
    <g class="breathe">
      <path d="M28 84 Q26 56 56 56 Q84 58 88 80 Q86 92 56 92 Q30 92 28 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 90 v10 M52 91 v10 M70 90 v10 M80 88 v11" fill="none" stroke="${c.line}" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M42 90 v10 M52 91 v10 M70 90 v10 M80 88 v11" fill="none" stroke="${c.body}" stroke-width="3.8" stroke-linecap="round"/>
      <path d="M40 100 l-2 4 m2 -4 l0 5 m0 -5 l2 4 M78 99 l-2 4 m2 -4 l0 5 m0 -5 l2 4" stroke="${CLAW}" stroke-width="1.5" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M73 44 Q69 22 78 18 Q85 16 89 23 Q91 34 86 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M77 42 Q74 27 80 21 Q84 18 86 23" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M78 62 Q78 44 92 44 Q104 44 112 60 Q112 68 104 70 Q90 72 78 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="108" cy="64" rx="4.4" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="106" cy="63" rx="1" ry="1.4" fill="${INK}"/><ellipse cx="110" cy="65" rx="1" ry="1.4" fill="${INK}"/>
      ${eye(88, 54, 2.8, E)}
    </g>`;
  },

  // ── Anteater — giant anteater, immense tubular down-curved snout, LONG sticky flicking tongue, huge bushy tail, side band (profile)
  anteater: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M42 66 Q16 54 8 76 Q4 92 20 94 Q14 84 30 82 Q16 88 22 98 Q34 86 46 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 68 Q14 82 20 92 M28 66 Q26 80 30 90" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="breathe">
      <path d="M38 78 Q38 58 62 58 Q86 58 90 76 Q86 90 60 90 Q38 90 38 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 60 Q64 66 74 88 Q66 90 60 88 Q50 74 46 62 Z" fill="${INK}" opacity=".85"/>
      <path d="M46 86 q-1 8 3 12 M76 84 q2 8 6 11" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M46 86 q-1 8 3 12 M76 84 q2 8 6 11" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M62 50 Q66 40 76 42 L104 78 Q104 86 96 84 Q88 76 78 66 Q68 58 62 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M98 80 l8 6 M100 78 l8 4" fill="none" stroke="${TONGUE}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M104 84 q6 4 3 10 q-4 -2 -3 -8" fill="none" stroke="${TONGUE}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="102" cy="80" rx="1.4" ry="1.1" fill="${INK}"/>
      <path d="M66 44 Q62 36 68 34 Q73 40 72 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(72, 52, 2.4, E)}
    </g>`;
  },

  // ── Pangolin — scaly anteater, body & long tail sheathed in overlapping keratin scales, tiny pointed snout (profile)
  pangolin: (c) => {
    const E = eyeInk(c);
    let scales = "";
    const rows = [[24, 32, 40, 48, 56, 64, 72], [30, 38, 46, 54, 62, 70], [40, 48, 56, 64], [50, 58, 66]];
    rows.forEach((xs, ri) => { const y = 58 + ri * 8; xs.forEach((x) => { scales += `<path d="M${x - 6} ${y} Q${x} ${y - 8} ${x + 6} ${y} Q${x} ${y + 3} ${x - 6} ${y} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`; }); });
    return `
    <g class="tail-wag">
      <path d="M40 84 Q18 90 10 78 Q8 70 18 68 Q14 76 26 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M14 74 Q10 78 14 82 M22 72 Q18 76 22 80" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 80 Q30 54 60 54 Q88 54 90 76 Q86 90 58 90 Q30 90 30 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${scales}
      <path d="M76 84 q1 8 5 11 M84 82 q3 7 7 10" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M76 84 q1 8 5 11 M84 82 q3 7 7 10" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M80 92 l-2 4 m2 -4 l0 5 m0 -5 l2 4" stroke="${CLAW}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M82 64 Q82 52 94 52 Q104 52 110 62 Q104 68 94 68 Q84 70 82 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="108" cy="62" rx="1.6" ry="1.2" fill="${INK}"/>
      ${eye(90, 59, 2.4, E)}
    </g>`;
  },

  // ── Armadillo — banded burrower, domed carapace of hinged bands, pointed snout, little ears, banded tail (profile)
  armadillo: (c) => {
    const E = eyeInk(c);
    let bands = "";
    for (let i = 0; i < 5; i++) { const x = 44 + i * 8; bands += `<path d="M${x} 56 Q${x + 2} 72 ${x + 3} 84" fill="none" stroke="${c.line}" stroke-width="1.8" opacity=".8"/>`; }
    return `
    <g class="tail-wag">
      ${tube("M32 84 Q14 86 12 74", c.shade, c.line, 6)}
      <path d="M16 76 l0 8 M22 74 l0 9 M28 74 l0 9" stroke="${c.line}" stroke-width="1" opacity=".6"/>
    </g>
    <g class="breathe">
      <path d="M32 84 Q30 52 60 52 Q90 52 88 84 Q60 92 32 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M36 84 Q36 74 42 74 Q48 74 48 84 M72 84 Q72 74 78 74 Q84 74 84 84" fill="${c.shade}" opacity=".5"/>
      ${bands}
      <ellipse cx="60" cy="60" rx="24" ry="6" fill="${c.shade}" opacity=".35"/>
      <path d="M42 86 v8 M52 87 v8 M70 87 v8 M80 86 v8" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M42 86 v8 M52 87 v8 M70 87 v8 M80 86 v8" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M80 50 Q78 42 84 42 Q88 48 86 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M78 64 Q78 50 92 50 Q102 50 110 62 Q102 68 92 68 Q80 70 78 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M106 60 l5 2 l-5 2 Z" fill="${INK}"/>
      ${eye(88, 58, 2.6, E)}
    </g>`;
  },

  // ── Tapir — stocky jungle browser, short prehensile trunk-snout, rounded rump, pale saddle mid-body, stumpy legs (profile)
  tapir: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M28 74 Q16 72 16 82", c.body, c.line, 4)}</g>
    <g class="breathe">
      <path d="M26 76 Q26 56 58 54 Q90 54 92 74 Q90 88 56 90 Q26 88 26 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 56 Q40 90 70 90 Q78 90 82 84 Q60 88 60 56 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M34 86 v13 M46 88 v12 M70 88 v12 M82 84 v14" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M34 86 v13 M46 88 v12 M70 88 v12 M82 84 v14" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 46 Q74 38 80 36 Q86 42 84 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 66 Q74 46 90 46 Q104 46 106 60 Q106 70 96 72 Q88 78 84 78 Q78 76 78 70 Q74 72 74 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M96 70 Q102 72 102 78 Q98 82 92 78 Q90 72 96 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="97" cy="77" rx="1.3" ry="1.6" fill="${INK}"/>
      ${eye(86, 58, 2.8, E)}
    </g>`;
  },

  // ── Hyrax — rock-dwelling guinea-pig lookalike, plump rounded body, tiny round ears, blunt face, dark dorsal spot (front)
  hyrax: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      <path d="M32 90 Q30 62 60 60 Q90 62 88 90 Q60 100 32 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="6" ry="8" fill="${c.shade}"/>
      <ellipse cx="60" cy="84" rx="16" ry="11" fill="${c.shade}" opacity=".45"/>
      <path d="M42 92 v8 M52 93 v8 M68 93 v8 M78 92 v8" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M42 92 v8 M52 93 v8 M68 93 v8 M78 92 v8" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="46" cy="42" rx="6" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="74" cy="42" rx="6" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M38 52 Q38 34 60 34 Q82 34 82 52 Q82 66 60 68 Q38 66 38 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="60" rx="8" ry="6" fill="${c.shade}"/>
      <ellipse cx="60" cy="57" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M60 60 q-5 5 -9 4 M60 60 q5 5 9 4" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${eyes(50, 70, 48, 2.8, E)}
    </g>`;
  },

  // ── Aye-Aye — spooky nocturnal lemur, huge glassy eyes, enormous bat ears, shaggy fur, long bony probing finger (front)
  ayeaye: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${pom(28, 74, 12, c.body, c.line, 10, 2.4)}
      ${pom(92, 74, 11, c.body, c.line, 9, 2.4)}
    </g>
    <g class="breathe">
      ${pom(60, 84, 22, c.body, c.line, 12, 2.6)}
      <ellipse cx="60" cy="88" rx="12" ry="10" fill="${c.shade}" opacity=".5"/>
      <path d="M46 92 Q40 100 34 98" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/>
      <path d="M46 92 Q40 100 34 98" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M74 90 Q86 92 96 84" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M74 90 Q86 92 96 84" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
      <path d="M96 84 l6 -6 l1 4" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M40 34 Q26 18 24 34 Q26 48 44 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M80 34 Q94 18 96 34 Q94 48 76 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M35 34 Q28 26 27 34 M85 34 Q92 26 93 34" fill="${PINK}" opacity=".55"/>
      <circle cx="60" cy="48" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="51" cy="46" r="8" fill="${CLAW}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="69" cy="46" r="8" fill="${CLAW}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="51" cy="46" r="3.6" fill="${INK}"/><circle cx="69" cy="46" r="3.6" fill="${INK}"/>
      <circle cx="49.5" cy="44.5" r="1.3" fill="#fff"/><circle cx="67.5" cy="44.5" r="1.3" fill="#fff"/>
      <ellipse cx="60" cy="58" rx="2.4" ry="1.8" fill="${INK}"/>
      <path d="M54 62 q6 4 12 0" fill="none" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Star-Nosed Mole — the pink 22-ray tentacled star nose, blind pinprick eyes, huge pink shovel foreclaws, cylinder body (front)
  starnosedmole: (c) => {
    const E = eyeInk(c);
    let star = "";
    for (let k = 0; k < 11; k++) { const a = (k * 360 / 11 - 90) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a); star += `<path d="M${(60 + 3 * ca).toFixed(1)} ${(72 + 3 * sa).toFixed(1)} L${(60 + 10 * ca).toFixed(1)} ${(72 + 10 * sa).toFixed(1)}" stroke="${PINK}" stroke-width="2.6" stroke-linecap="round"/>`; }
    return `
    <g class="breathe">
      <path d="M34 88 Q32 62 60 60 Q88 62 86 88 Q60 98 34 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 70 Q60 62 80 70 M40 80 Q60 74 80 80" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <path d="M32 78 Q18 76 16 88 Q22 92 30 86 Q26 82 34 82 Z" fill="${PINK}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M18 84 l0 6 M23 82 l0 7 M28 82 l0 6" stroke="${c.line}" stroke-width="1" opacity=".6"/>
      <path d="M88 78 Q102 76 104 88 Q98 92 90 86 Q94 82 86 82 Z" fill="${PINK}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M102 84 l0 6 M97 82 l0 7 M92 82 l0 6" stroke="${c.line}" stroke-width="1" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="54" rx="20" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${star}
      <circle cx="60" cy="72" r="3.4" fill="${PINK}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="53" cy="52" r="1.6" fill="${INK}"/><circle cx="67" cy="52" r="1.6" fill="${INK}"/>
    </g>`;
  },

  // ── Naked Mole Rat — hairless wrinkled tube of a body, big protruding buck incisors, pinprick eyes, stubby legs (profile)
  nakedmolerat: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M32 78 Q16 78 14 70", c.shade, c.line, 4)}</g>
    <g class="breathe">
      <path d="M30 76 Q30 58 62 58 Q90 58 90 74 Q88 88 60 88 Q30 88 30 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 62 Q42 84 44 86 M56 60 Q56 86 58 88 M70 60 Q70 84 72 86" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      <path d="M46 84 q-1 6 3 8 M74 84 q1 6 5 8" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/>
      <path d="M46 84 q-1 6 3 8 M74 84 q1 6 5 8" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 62 Q78 48 92 48 Q104 48 108 60 Q104 68 96 68 Q80 70 78 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M96 66 Q94 72 97 76 L100 76 Q101 70 100 66 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M100 66 Q100 71 102 75 L105 75 Q105 70 104 66 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M84 52 q4 3 8 2 M88 60 q4 2 8 1" fill="none" stroke="${c.shade}" stroke-width="1.2" opacity=".7"/>
      <circle cx="88" cy="58" r="1.4" fill="${INK}"/>
    </g>`;
  },

  // ── Solenodon — venomous shrew-relative, extra-long flexible tubular snout, long naked tail, long digging claws (profile)
  solenodon: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M34 84 Q14 88 10 76", PINK, c.line, 4)}</g>
    <g class="breathe">
      <path d="M32 80 Q32 60 60 60 Q86 60 88 78 Q84 90 58 90 Q32 90 32 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 86 Q60 92 74 86 Q60 90 42 86 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M44 86 q-1 8 3 11 M70 86 q1 8 5 11" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M44 86 q-1 8 3 11 M70 86 q1 8 5 11" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M45 96 l-2 4 m2 -4 l0 5 m0 -5 l2 4 M73 96 l-2 4 m2 -4 l0 5 m0 -5 l2 4" stroke="${CLAW}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M74 48 Q70 40 76 38 Q81 44 79 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M70 66 Q70 50 84 50 Q94 50 98 58 L112 66 Q112 72 104 70 L96 66 Q86 70 70 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M108 68 l4 1 l-4 2 Z" fill="${PINK}" stroke="${c.line}" stroke-width="0.9" stroke-linejoin="round"/>
      <path d="M96 64 l12 -1 M96 68 l12 2" stroke="${c.line}" stroke-width="0.8" opacity=".55"/>
      ${eye(82, 58, 2.6, E)}
    </g>`;
  },
};

export const ROSTER_ODDBALLS = [
  { n: "Platypus",        e: "🦆", tier: 3, float: false },
  { n: "Echidna",         e: "🦔", tier: 3, float: false },
  { n: "Opossum",         e: "🐀", tier: 1, float: false },
  { n: "Wombat",          e: "🐻", tier: 2, float: false },
  { n: "Tasmanian Devil", e: "😈", tier: 3, float: false },
  { n: "Quokka",          e: "🐹", tier: 2, float: false },
  { n: "Wallaby",         e: "🦘", tier: 2, float: false },
  { n: "Numbat",          e: "🐿️", tier: 3, float: false },
  { n: "Bilby",           e: "🐰", tier: 3, float: false },
  { n: "Bandicoot",       e: "🐁", tier: 1, float: false },
  { n: "Aardvark",        e: "🐽", tier: 3, float: false },
  { n: "Anteater",        e: "🐜", tier: 2, float: false },
  { n: "Pangolin",        e: "🦎", tier: 3, float: false },
  { n: "Armadillo",       e: "🛡️", tier: 2, float: false },
  { n: "Tapir",           e: "🐗", tier: 3, float: false },
  { n: "Hyrax",           e: "🐭", tier: 2, float: false },
  { n: "Aye-Aye",         e: "🐒", tier: 3, float: false },
  { n: "Star-Nosed Mole", e: "⭐", tier: 3, float: false },
  { n: "Naked Mole Rat",  e: "🦷", tier: 3, float: false },
  { n: "Solenodon",       e: "🐀", tier: 3, float: false },
];
