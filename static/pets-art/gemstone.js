// pets-art/gemstone.js — BESPOKE hand-drawn SVG art for GEMSTONE creatures (NADO Pets).
// Crystalline gem-themed beasts: a recognizable ANIMAL base dressed in faceted/crystal styling —
// angular facet planes (tint/deepen of the coat), sharp facet edge-lines, and star sparkle glints.
// Each entry: slug -> (c) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,64),
// within x,y ∈ [8,114]. Palette-driven: c.body (main) / c.shade (accent) / c.line (outline). Real hues
// are recoloured at hatch, so gem colours are NOT hardcoded — facets derive from c via tint()/deepen();
// only universal accents are fixed: sparkle glints #eafff4 / gold #ffd24a, horns/beaks #f2c94c, teeth #fff.
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/wings/fins <g class="tail-wag">.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// fixed crystalline accents that stay constant across coats
const SPK = "#eafff4", GLD = "#ffd24a", HORN = "#f2c94c";
// a 4-point sparkle glint (the "crystal shine")
const spark = (x, y, s, col = SPK) => `<path d="M${x} ${y - s} L${(x + s * 0.3).toFixed(1)} ${(y - s * 0.3).toFixed(1)} L${x + s} ${y} L${(x + s * 0.3).toFixed(1)} ${(y + s * 0.3).toFixed(1)} L${x} ${y + s} L${(x - s * 0.3).toFixed(1)} ${(y + s * 0.3).toFixed(1)} L${x - s} ${y} L${(x - s * 0.3).toFixed(1)} ${(y - s * 0.3).toFixed(1)} Z" fill="${col}"/>`;

export const ART_GEMSTONE = {
  // ── Ruby Golem — upright cut-gem stone giant, faceted body, stubby limbs, glowing carved face (t3, front) ──
  rubygolem: (c) => {
    const B = belly(c), L = tint(c.body, 0.34), D = deepen(c.body, 0.22);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M42 60 L26 62 L24 82 L38 84 L44 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M78 60 L94 62 L96 82 L82 84 L76 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 16 L84 40 L82 78 L70 104 L50 104 L38 78 L36 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 16 L84 40 L60 52 Z" fill="${L}" opacity=".55"/>
      <path d="M60 16 L36 40 L60 52 Z" fill="${D}" opacity=".5"/>
      <path d="M38 78 L50 104 L60 84 Z" fill="${D}" opacity=".45"/>
      <path d="M82 78 L70 104 L60 84 Z" fill="${L}" opacity=".45"/>
      <path d="M60 16 L60 52 L60 84 M36 40 L60 52 L84 40 M38 78 L60 84 L82 78" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <rect x="46" y="99" width="10" height="11" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <rect x="64" y="99" width="10" height="11" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="62" rx="15" ry="11" fill="${B}" opacity=".85"/>
      ${ceye(53, 60, 4)}${ceye(67, 60, 4)}
      <path d="M60 65 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      ${smile(60, 69, 3, c.line)}
      ${spark(74, 34, 3)}${spark(46, 72, 2.4, GLD)}
    </g>`;
  },

  // ── Sapphire Sprite — floating chibi gem-drop, crystal shard wings, no legs, bright cut facets (t3, float) ──
  sapphiresprite: (c) => {
    const B = belly(c), L = tint(c.body, 0.34), D = deepen(c.body, 0.22), W = tint(c.body, 0.5);
    return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      <path d="M52 56 L30 40 L34 60 L26 72 L50 66 Z" fill="${W}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
      <path d="M68 56 L90 40 L86 60 L94 72 L70 66 Z" fill="${W}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M60 30 L80 54 L72 88 L48 88 L40 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 30 L80 54 L60 62 Z" fill="${L}" opacity=".6"/>
      <path d="M60 30 L40 54 L60 62 Z" fill="${D}" opacity=".5"/>
      <path d="M48 88 L60 62 L72 88 Z" fill="${B}" opacity=".5"/>
      <path d="M60 30 L60 62 M40 54 L60 62 L80 54 M48 88 L60 62 L72 88" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <ellipse cx="60" cy="64" rx="12" ry="9" fill="${B}" opacity=".8"/>
      ${ceye(53, 62, 4)}${ceye(67, 62, 4)}
      <path d="M60 67 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 70, 2.6, c.line)}
      ${spark(70, 44, 3)}${spark(48, 50, 2.2, GLD)}${spark(60, 84, 2.2)}
    </g>`;
  },

  // ── Emerald Serpent — reared cobra, coiled base + flaring faceted hood, forked tongue, jewel scales (t3) ──
  emeraldserpent: (c) => {
    const B = belly(c), L = tint(c.body, 0.34), D = deepen(c.body, 0.22), E = eyeInk(c);
    return `
    ${floorShadow(58, 108, 30)}
    <g class="tail-wag">
      <path d="M78 96 Q96 92 92 80 Q88 72 80 76 Q86 82 80 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M26 98 Q18 84 34 78 Q52 72 70 78 Q88 84 84 96 Q58 106 26 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 92 Q56 100 78 92 Q56 96 34 92 Z" fill="${B}" opacity=".7"/>
      <path d="M50 84 Q46 66 42 52 Q40 42 52 38 Q46 30 54 24 Q60 20 66 24 Q74 30 68 38 Q80 42 78 52 Q74 66 70 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 52 L60 45 L78 52 L60 60 Z" fill="${L}" opacity=".45"/>
      <path d="M42 52 L60 45 L78 52 M60 45 L60 60" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <ellipse cx="60" cy="30" rx="9" ry="7" fill="${B}" opacity=".75"/>
      ${eyes(55, 65, 29, 2.6, E)}
      <path d="M60 33 l-1.8 2 h3.6 Z" fill="${INK}"/>
      <path d="M60 36 v6 M56 46 l4 -2 l4 2" fill="none" stroke="${GLD}" stroke-width="1.4" stroke-linecap="round"/>
      ${spark(68, 28, 2.6)}${spark(46, 88, 2.2, GLD)}
    </g>`;
  },

  // ── Diamond Beast — brilliant faceted big cat, front sitting, chest facet, whiskers, bright glints (t4) ──
  diamondbeast: (c) => {
    const B = belly(c), L = tint(c.body, 0.42), D = deepen(c.body, 0.2);
    return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag"><path d="M80 98 Q104 94 100 74 Q98 64 88 66 Q96 72 90 84 Q84 92 74 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 114 C30 114 26 92 31 72 C33 60 36 54 41 49 L31 22 L54 43 Q60 39 66 43 L89 22 L79 49 C84 54 87 60 89 72 C94 92 90 114 60 114 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M37 30 L50 44 Q44 47 41 51 Z" fill="${D}"/><path d="M83 30 L70 44 Q76 47 79 51 Z" fill="${D}"/>
      <path d="M60 60 L42 84 L60 112 L78 84 Z" fill="${B}" opacity=".55"/>
      <path d="M60 60 L42 84 L60 96 Z" fill="${L}" opacity=".4"/>
      <path d="M60 60 L60 112 M42 84 L60 96 L78 84" fill="none" stroke="${c.line}" stroke-width="1" opacity=".35"/>
      <ellipse cx="60" cy="70" rx="20" ry="15" fill="${B}" opacity=".7"/>
      ${ceye(51, 66, 4.2)}${ceye(69, 66, 4.2)}
      <path d="M60 74 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 77 v3 M60 80 q-4 3 -8 2 M60 80 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      <path d="M34 68 h-13 M35 73 h-14 M86 68 h13 M85 73 h14" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round" opacity=".5"/>
      ${spark(74, 40, 3.4)}${spark(46, 54, 2.6)}${spark(60, 100, 2.4, GLD)}
    </g>`;
  },

  // ── Amethyst Wyrm — legless spiny gem-dragon, twin crystal horns, spine ridges, curling barbed tail (t4) ──
  amethystwyrm: (c) => {
    const B = belly(c), S = tint(c.body, 0.5), E = eyeInk(c);
    return `
    ${floorShadow(56, 110, 32)}
    <g class="tail-wag">
      ${tube("M48 84 Q22 90 18 66 Q16 54 28 55", c.body, c.line, 9)}
      <path d="M28 55 l-9 -4 l3 9 l-8 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M32 86 Q28 60 56 58 Q82 56 86 76 Q86 88 70 88 Q50 90 40 88 Q32 88 32 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 84 Q58 90 74 84 Q58 88 42 84 Z" fill="${B}" opacity=".7"/>
      ${[[42, 60], [52, 56], [62, 56], [72, 60]].map(([x, y]) => `<path d="M${x} ${y} l4 -11 l4 11 Z" fill="${S}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M80 46 Q78 30 68 26 Q74 36 76 50 Z" fill="${S}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M92 44 Q92 28 82 26 Q86 36 86 50 Z" fill="${S}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M72 68 Q72 48 90 48 Q106 48 106 62 Q106 68 98 70 L110 72 Q108 78 98 76 Q74 78 72 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M102 72 l1.4 3.4 l1.6 -3 Z" fill="#fff" stroke="${c.line}" stroke-width="0.5"/>
      <path d="M88 46 L82 58 L90 62 Z" fill="${tint(c.body, 0.34)}" opacity=".4"/>
      ${eye(88, 60, 3.2, E)}
      ${spark(58, 48, 2.6)}${spark(44, 80, 2.2, GLD)}
    </g>`;
  },

  // ── Opal Fox — iridescent fox, pointed ears, pale-tipped bushy tail, scattered opal glints (t4, front) ──
  opalfox: (c) => {
    const B = belly(c), D = deepen(c.body, 0.22);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag"><path d="M80 100 Q108 96 104 72 Q102 60 90 64 Q100 72 92 86 Q86 96 74 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M96 66 Q104 70 100 82" fill="none" stroke="${B}" stroke-width="4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M60 112 C34 112 30 92 34 74 C36 62 40 56 46 52 L36 26 L54 44 Q60 40 66 44 L84 26 L74 52 C80 56 84 62 86 74 C90 92 86 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M41 32 L52 46 Q47 49 44 53 Z" fill="${D}"/><path d="M79 32 L68 46 Q73 49 76 53 Z" fill="${D}"/>
      <path d="M44 82 Q60 104 76 82 Q60 92 44 82 Z" fill="${B}" opacity=".8"/>
      <ellipse cx="60" cy="66" rx="17" ry="13" fill="${B}" opacity=".55"/>
      ${ceye(52, 62, 4)}${ceye(68, 62, 4)}
      <path d="M60 68 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M60 71 v3 M60 74 q-4 3 -7 2 M60 74 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${spark(72, 50, 2.8)}${spark(48, 54, 2.4, GLD)}${spark(60, 96, 2.2)}${spark(40, 72, 1.8)}
    </g>`;
  },

  // ── Topaz Hound — faceted golden dog, floppy ears, front sitting, warm crystal glint (t3) ──
  topazhound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag"><path d="M78 100 Q100 98 98 82 Q96 74 88 76 Q94 82 88 90 Q84 96 74 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 112 C36 112 32 92 36 76 C38 64 42 58 48 54 Q52 46 60 46 Q68 46 72 54 C78 58 82 64 84 76 C88 92 84 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 52 Q34 54 34 70 Q34 80 44 78 Q42 64 50 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M74 52 Q86 54 86 70 Q86 80 76 78 Q78 64 70 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M44 86 Q60 106 76 86 Q60 96 44 86 Z" fill="${B}" opacity=".8"/>
      <ellipse cx="60" cy="68" rx="16" ry="13" fill="${B}" opacity=".55"/>
      ${ceye(52, 64, 4)}${ceye(68, 64, 4)}
      <path d="M60 70 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      <path d="M60 73 v3 M60 76 q-4 3 -7 2 M60 76 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${spark(72, 52, 2.8)}${spark(48, 78, 2.2, GLD)}
    </g>`;
  },

  // ── Jade Turtle — domed jade shell with hex facet-plates, stubby legs, poking head, tiny tail (t3, side) ──
  jadeturtle: (c) => {
    const B = belly(c), L = tint(c.body, 0.34), E = eyeInk(c);
    return `
    ${floorShadow(60, 110, 32)}
    <g class="breathe">
      <ellipse cx="40" cy="96" rx="8" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="78" cy="96" rx="8" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <path d="M84 80 Q104 78 104 66 Q104 56 92 58 Q84 62 82 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${eye(96, 64, 3, E)}
      <path d="M99 70 q4 1 6 -1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M30 82 L18 84 L28 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M28 86 Q26 54 60 52 Q94 54 92 86 Q60 94 28 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M30 82 Q60 92 90 82 L90 86 Q60 96 30 86 Z" fill="${B}" opacity=".8"/>
      <path d="M60 54 L44 64 L48 80 L60 84 L72 80 L76 64 Z" fill="${L}" opacity=".5" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M60 54 L60 52 M44 64 L36 78 M76 64 L84 78 M48 80 L40 88 M72 80 L80 88" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      ${spark(50, 66, 2.6)}${spark(72, 72, 2.2, GLD)}
    </g>`;
  },

  // ── Onyx Panther — sleek melanistic gem-cat, low side prowl, glossy sheen facet, long tail (t4) ──
  onyxpanther: (c) => {
    const B = belly(c), L = tint(c.body, 0.5), D = deepen(c.body, 0.28);
    return `
    ${floorShadow(58, 110, 32)}
    <g class="tail-wag"><path d="M30 84 Q10 88 12 66 Q13 56 22 58 Q16 66 22 74 Q27 80 34 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 82 Q24 64 46 62 Q58 60 74 64 L74 90 L66 90 L64 82 L48 82 L46 90 L34 90 L34 80 Q28 82 26 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M32 78 Q52 86 74 78 Q52 84 32 78 Z" fill="${L}" opacity=".3"/>
      <path d="M40 70 L70 68 L56 84 Z" fill="${tint(c.body, 0.35)}" opacity=".3"/>
    </g>
    <g class="head-tilt">
      <path d="M74 50 L76 40 L86 48 Z" fill="${D}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="84" cy="60" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M84 62 Q92 72 100 62 Q96 68 92 68 Q87 68 84 62 Z" fill="${L}" opacity=".4"/>
      <path d="M96 62 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      <path d="M84 44 L78 56 L86 60 Z" fill="${tint(c.body, 0.72)}" opacity=".4"/>
      ${eye(90, 57, 3.2, eyeInk(c))}
      <path d="M68 60 q-4 1 -6 -1" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      ${spark(66, 56, 2.8)}${spark(44, 74, 2.2, GLD)}
    </g>`;
  },

  // ── Pearl Jelly — nacreous jellyfish, glossy smooth dome, trailing tentacles, cheek blush (t3, float) ──
  pearljelly: (c) => {
    const B = belly(c), L = tint(c.body, 0.5);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${[42, 50, 60, 70, 78].map((x, i) => tube(`M${x} 72 q${i % 2 ? 6 : -6} 14 ${i % 2 ? 2 : -2} 30`, c.body, c.line, 4)).join("")}
    </g>
    <g class="breathe">
      <path d="M28 66 Q26 34 60 34 Q94 34 92 66 Q88 76 78 72 Q68 78 60 72 Q52 78 42 72 Q32 76 28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 44 Q54 36 66 40 Q52 44 46 54 Z" fill="#fff" opacity=".5"/>
      <ellipse cx="74" cy="52" rx="6" ry="8" fill="${L}" opacity=".4"/>
      <ellipse cx="60" cy="60" rx="22" ry="10" fill="${B}" opacity=".5"/>
      ${ceye(52, 58, 3.8)}${ceye(68, 58, 3.8)}
      ${smile(60, 63, 3.4, c.line)}
      <circle cx="45" cy="61" r="2.6" fill="#fff" opacity=".4"/><circle cx="75" cy="61" r="2.6" fill="#fff" opacity=".4"/>
      ${spark(74, 42, 2.6)}${spark(46, 44, 2.2, GLD)}
    </g>`;
  },

  // ── Quartz Golem — clear-crystal golem, spiky point crown + shoulder clusters, faceted body (t3, front) ──
  quartzgolem: (c) => {
    const B = belly(c), L = tint(c.body, 0.4), D = deepen(c.body, 0.2), P = tint(c.body, 0.55);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M44 58 L30 60 L28 82 L42 84 L46 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M76 58 L90 60 L92 82 L78 84 L74 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M42 54 L34 34 L48 50 Z" fill="${P}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 54 L86 34 L72 50 Z" fill="${P}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 34 L50 16 L60 32 L70 16 L68 34 Z" fill="${P}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 52 L60 46 L76 52 L82 78 L72 106 L48 106 L38 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 46 L76 52 L60 62 Z" fill="${L}" opacity=".5"/>
      <path d="M60 46 L44 52 L60 62 Z" fill="${D}" opacity=".4"/>
      <path d="M60 62 L60 106 M44 52 L60 62 L76 52 M40 80 L60 88 L80 80" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <rect x="46" y="100" width="10" height="10" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <rect x="64" y="100" width="10" height="10" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="14" ry="10" fill="${B}" opacity=".8"/>
      ${ceye(53, 64, 3.8)}${ceye(67, 64, 3.8)}
      <path d="M60 68 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      ${smile(60, 72, 2.8, c.line)}
      ${spark(58, 24, 3)}${spark(46, 44, 2.4, GLD)}${spark(74, 44, 2.4)}
    </g>`;
  },

  // ── Obsidian Wolf — volcanic-glass wolf, sharp angular snout facet, pointed ears, glossy sheen (t4, front) ──
  obsidianwolf: (c) => {
    const B = belly(c), L = tint(c.body, 0.5), D = deepen(c.body, 0.28);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag"><path d="M80 100 Q106 98 104 76 Q102 66 90 70 Q98 76 92 88 Q86 96 74 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 112 C34 112 30 92 34 74 C36 62 40 56 46 52 L38 28 L56 46 Q60 43 64 46 L82 28 L74 52 C80 56 84 62 86 74 C90 92 86 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M41 34 L54 48 Q49 50 46 54 Z" fill="${D}"/><path d="M79 34 L66 48 Q71 50 74 54 Z" fill="${D}"/>
      <path d="M60 58 L46 84 L60 112 L74 84 Z" fill="${L}" opacity=".3"/>
      <path d="M60 66 L50 78 L60 88 L70 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M60 88 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      <path d="M60 91 v3" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${ceye(51, 62, 4)}${ceye(69, 62, 4)}
      <path d="M46 58 q5 -3 9 0 M65 58 q4 -3 9 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
      ${spark(72, 44, 3)}${spark(48, 50, 2.4)}${spark(60, 100, 2.4, GLD)}
    </g>`;
  },

  // ── Amber Beetle — beetle sealed in a translucent amber blob, split carapace, antennae, six legs (t2) ──
  amberbeetle: (c) => {
    const L = tint(c.body, 0.4), A = tint(c.body, 0.55), E = eyeInk(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="breathe">
      <path d="M60 16 Q92 22 96 60 Q98 92 60 104 Q22 92 24 60 Q28 22 60 16 Z" fill="${A}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".92"/>
      <path d="M40 30 Q56 22 68 28 Q52 32 44 46 Z" fill="#fff" opacity=".35"/>
      <g stroke="${c.line}" stroke-width="3" stroke-linecap="round" fill="none">
        <path d="M46 58 l-12 -6 M46 66 l-13 2 M46 74 l-11 8"/>
        <path d="M74 58 l12 -6 M74 66 l13 2 M74 74 l11 8"/>
      </g>
      <path d="M52 34 Q52 26 60 26 Q68 26 68 34 Q68 40 60 40 Q52 40 52 34 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 27 l-5 -7 M65 27 l5 -7" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M44 44 Q44 38 60 38 Q76 38 76 44 L74 82 Q60 92 46 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 40 L60 88" stroke="${c.line}" stroke-width="2"/>
      <path d="M52 48 L48 60 M68 48 L72 60 M50 66 L48 78 M70 66 L72 78" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      <path d="M48 46 Q54 42 58 46 L54 52 Z" fill="${L}" opacity=".5"/>
      ${eyes(56, 64, 33, 2.2, E)}
      ${spark(80, 40, 2.8)}${spark(38, 70, 2.2, GLD)}
    </g>`;
  },

  // ── Garnet Drake — chubby four-legged winged gem-dragon, spine ridges, gold horns, spade tail (t4, side) ──
  garnetdrake: (c) => {
    const B = belly(c), S = tint(c.body, 0.5), E = eyeInk(c);
    return `
    ${floorShadow(56, 112, 32)}
    <g class="tail-wag">
      <path d="M42 86 Q16 90 14 68 Q13 56 25 57 Q17 65 24 74 Q31 81 42 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M16 66 l-8 -4 l4 8 l-9 1 l7 6 Z" fill="${S}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M60 54 Q42 28 36 46 Q49 45 55 57 Q45 52 42 64 Q56 56 66 62 Z" fill="${tint(c.body, 0.45)}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 86 C34 64 48 56 66 56 C74 56 80 59 84 64 L92 56 C104 54 108 64 103 72 C99 78 91 76 88 72 C88 84 82 92 72 92 L72 106 L64 106 L64 92 L48 92 L48 106 L40 106 L40 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[46, 58, 70].map(x => `<path d="M${x} 58 l4 -9 l4 9 Z" fill="${S}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
      <path d="M52 86 Q66 94 84 86 Q68 90 52 86 Z" fill="${B}" opacity=".8"/>
      <path d="M88 58 Q84 44 76 42 Q82 50 82 60 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M97 58 Q95 44 86 40 Q90 50 91 60 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(92, 66, 3.2, E)}
      <path d="M101 73 l1.4 3.4 l1.6 -3 Z" fill="#fff" stroke="${c.line}" stroke-width="0.5"/>
      ${spark(60, 70, 2.6)}${spark(44, 80, 2.2, GLD)}
    </g>`;
  },

  // ── Peridot Newt — sprawled salamander, long curling tail, four splayed legs, dorsal facet spots (t2) ──
  peridotnewt: (c) => {
    const B = belly(c), L = tint(c.body, 0.5), E = eyeInk(c);
    return `
    ${floorShadow(58, 108, 32)}
    <g class="tail-wag"><path d="M34 82 Q14 84 10 70 Q8 62 18 62 Q14 70 22 74 Q28 78 34 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M40 78 l-6 12 M52 82 l-3 12 M70 82 l3 12 M82 78 l6 12" stroke="${c.line}" stroke-width="6.4" stroke-linecap="round"/>
      <path d="M40 78 l-6 12 M52 82 l-3 12 M70 82 l3 12 M82 78 l6 12" stroke="${c.shade}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M30 74 Q30 62 54 62 Q78 62 88 68 Q96 72 88 78 Q78 84 54 84 Q34 84 30 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 80 Q58 86 84 78 Q58 82 36 80 Z" fill="${B}" opacity=".7"/>
      <path d="M84 66 Q102 66 102 76 Q102 84 90 82 Q82 80 82 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M92 80 q5 1 8 -1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(93, 72, 3, E)}
      ${[46, 58, 70].map(x => `<path d="M${x} 65 l3 3 l-3 3 l-3 -3 Z" fill="${L}" opacity=".55"/>`).join("")}
      ${spark(64, 72, 2.4)}${spark(48, 80, 2, GLD)}
    </g>`;
  },

  // ── Citrine Bird — plump gem songbird, faceted wing, gold beak, forked tail (t2, float, faces right) ──
  citrinebird: (c) => {
    const B = belly(c), L = tint(c.body, 0.4), E = eyeInk(c);
    return `
    ${floorShadow(58, 108, 24)}
    <g class="tail-wag"><path d="M30 62 L10 52 L14 64 L10 76 L32 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M34 58 Q34 38 60 38 Q86 40 90 60 Q90 80 62 82 Q36 80 34 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 66 Q58 82 76 74 Q64 78 54 72 Q46 68 44 66 Z" fill="${B}" opacity=".75"/>
      <path d="M52 54 L74 50 L64 68 L48 64 Z" fill="${L}" opacity=".55" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M74 50 L64 68 M52 54 L64 68" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <path d="M88 56 L102 60 L88 64 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(82, 54, 3.2, E)}
      ${spark(56, 46, 2.6)}${spark(46, 70, 2.2, GLD)}
    </g>`;
  },

  // ── Turquoise Fish — side gem-fish, diamond scale facets, fanned fins, round tail (t2, float, faces right) ──
  turquoisefish: (c) => {
    const B = belly(c), L = tint(c.body, 0.4), E = eyeInk(c);
    return `
    ${floorShadow(58, 108, 26)}
    <g class="tail-wag"><path d="M40 62 L14 44 Q9 62 15 80 L40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M34 46 Q52 40 58 50 Q46 50 40 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 78 Q54 84 62 76 Q50 76 44 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M30 62 Q30 40 62 40 Q92 42 102 62 Q92 82 62 84 Q34 82 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 66 Q54 78 84 70 Q60 74 44 70 Q37 68 34 66 Z" fill="${B}" opacity=".6"/>
      ${[[52, 54], [64, 52], [76, 56], [58, 64], [70, 64]].map(([x, y]) => `<path d="M${x} ${y - 4} l5 4 l-5 4 l-5 -4 Z" fill="${L}" opacity=".5" stroke="${c.line}" stroke-width="0.8" stroke-linejoin="round"/>`).join("")}
      ${eye(88, 58, 3.4, E)}
      <path d="M92 66 q4 2 8 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${spark(50, 48, 2.6)}${spark(80, 74, 2.2, GLD)}
    </g>`;
  },

  // ── Moonstone Owl — pale glowing owl, big luminous eyes, ear tufts, faceted breast feathers (t3, front) ──
  moonstoneowl: (c) => {
    const B = belly(c), L = tint(c.body, 0.4), G = tint(c.body, 0.3);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M30 62 Q18 74 24 92 Q32 84 38 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M90 62 Q102 74 96 92 Q88 84 82 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M42 40 L36 20 L52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M78 40 L84 20 L68 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 108 Q30 106 30 66 Q30 34 60 32 Q90 34 90 66 Q90 106 60 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 60 Q42 62 40 88 Q46 102 60 102 Q74 102 80 88 Q78 62 60 60 Z" fill="${B}" opacity=".7"/>
      ${[[50, 74], [60, 72], [70, 74], [54, 86], [66, 86]].map(([x, y]) => `<path d="M${x} ${y - 4} l4 4 l-4 4 l-4 -4 Z" fill="${L}" opacity=".45"/>`).join("")}
      <circle cx="50" cy="54" r="13" fill="${G}" opacity=".5"/>
      <circle cx="70" cy="54" r="13" fill="${G}" opacity=".5"/>
      ${ceye(50, 54, 6.5)}${ceye(70, 54, 6.5)}
      <path d="M60 60 l-4 5 h8 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1"/>
      ${spark(60, 26, 3)}${spark(44, 64, 2.2, GLD)}${spark(78, 66, 2.2)}
    </g>`;
  },

  // ── Sunstone Lion — radiant lion, sunburst crystal-ray mane, front sitting, tuft tail, gold glints (t4) ──
  sunstonelion: (c) => {
    const B = belly(c), M = tint(c.body, 0.18);
    const rays = Array.from({ length: 12 }, (_, i) => {
      const a = i * 30 * Math.PI / 180;
      const x2 = 60 + 41 * Math.cos(a), y2 = 52 + 41 * Math.sin(a);
      const px = 60 + 27 * Math.cos(a + 0.28), py = 52 + 27 * Math.sin(a + 0.28);
      const qx = 60 + 27 * Math.cos(a - 0.28), qy = 52 + 27 * Math.sin(a - 0.28);
      return `<path d="M${px.toFixed(1)} ${py.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)} L${qx.toFixed(1)} ${qy.toFixed(1)} Z" fill="${M}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`;
    }).join("");
    return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag"><path d="M80 100 Q104 96 100 76 Q98 66 88 68 Q96 74 90 86 Q84 94 74 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="90" cy="72" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="breathe">
      <path d="M60 114 C36 114 32 94 36 78 C40 62 48 58 60 58 C72 58 80 62 84 78 C88 94 84 114 60 114 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 86 Q60 104 74 86 Q60 96 46 86 Z" fill="${B}" opacity=".7"/>
    </g>
    <g class="head-tilt">
      ${rays}
      <circle cx="60" cy="52" r="24" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M44 54 Q60 74 76 54 Q76 66 60 70 Q44 66 44 54 Z" fill="${B}" opacity=".55"/>
      ${ceye(51, 48, 4.2)}${ceye(69, 48, 4.2)}
      <path d="M60 56 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 59 v3 M60 62 q-4 3 -7 2 M60 62 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${spark(60, 18, 3.4, GLD)}${spark(28, 52, 2.6)}${spark(92, 52, 2.6)}
    </g>`;
  },

  // ── Lapis Whale — deep-blue whale with gold pyrite flecks, tail fluke, pectoral fin, spout, smile (t4, float) ──
  lapiswhale: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 110, 34)}
    <g class="tail-wag"><path d="M28 64 L10 50 Q6 60 10 66 Q6 72 12 82 L30 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 66 Q26 42 60 42 Q98 42 104 62 Q106 74 92 80 Q60 88 40 84 Q26 80 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 74 Q60 86 92 78 Q88 84 60 86 Q40 84 34 74 Z" fill="${B}" opacity=".7"/>
      <path d="M40 72 q6 4 12 0 M56 76 q6 3 12 0 M74 74 q5 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      <path d="M58 78 Q56 90 48 92 Q52 82 52 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 44 Q76 32 82 28 M78 44 Q80 34 86 32" fill="none" stroke="${tint(c.body, 0.6)}" stroke-width="2.4" stroke-linecap="round"/>
      ${eye(88, 60, 3.2, E)}
      <path d="M92 68 q6 2 10 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${spark(50, 58, 2.4, GLD)}${spark(66, 54, 2, GLD)}${spark(74, 64, 1.8, GLD)}${spark(42, 66, 1.8, GLD)}${spark(80, 54, 2.2)}
    </g>`;
  },
};

export const ROSTER_GEMSTONE = [
  { n: "Ruby Golem",      e: "🗿", tier: 3, float: false },
  { n: "Sapphire Sprite", e: "🧚", tier: 3, float: true  },
  { n: "Emerald Serpent", e: "🐍", tier: 3, float: false },
  { n: "Diamond Beast",   e: "🐯", tier: 4, float: false },
  { n: "Amethyst Wyrm",   e: "🐲", tier: 4, float: false },
  { n: "Opal Fox",        e: "🦊", tier: 4, float: false },
  { n: "Topaz Hound",     e: "🐕", tier: 3, float: false },
  { n: "Jade Turtle",     e: "🐢", tier: 3, float: false },
  { n: "Onyx Panther",    e: "🐆", tier: 4, float: false },
  { n: "Pearl Jelly",     e: "🪼", tier: 3, float: true  },
  { n: "Quartz Golem",    e: "🗿", tier: 3, float: false },
  { n: "Obsidian Wolf",   e: "🐺", tier: 4, float: false },
  { n: "Amber Beetle",    e: "🪲", tier: 2, float: false },
  { n: "Garnet Drake",    e: "🐉", tier: 4, float: false },
  { n: "Peridot Newt",    e: "🦎", tier: 2, float: false },
  { n: "Citrine Bird",    e: "🐦", tier: 2, float: true  },
  { n: "Turquoise Fish",  e: "🐟", tier: 2, float: true  },
  { n: "Moonstone Owl",   e: "🦉", tier: 3, float: false },
  { n: "Sunstone Lion",   e: "🦁", tier: 4, float: false },
  { n: "Lapis Whale",     e: "🐋", tier: 4, float: true  },
];
