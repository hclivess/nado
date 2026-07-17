// pets-art/plants.js — BESPOKE hand-drawn SVG art for PLANTS (NADO Pets).
// Living-flora creatures, cute. HOUSE STYLE (see METHOD): ONE continuous silhouette per body,
// two-tone shading (belly()+c.shade), a clean cute face (ceye), leaves/vines/petals tucked so
// NOTHING floats, everything grounded with floorShadow. viewBox 0 0 120 120, centred ~(60,64),
// kept within x,y ∈ [8,114]. Colours come from the coat c (c.body main / c.shade accent /
// c.line outline) so the game recolours every pet at hatch; leaf/petal accents derive from c
// via tint()/deepen(); only the universal beak accent is fixed.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const BEAK = "#f2a03b"; // universal warm beak (only fixed accent)

// a hand-drawn leaf/petal: pointed lens from base (bx,by) to tip (tx,ty), with a centre vein
const leaf = (bx, by, tx, ty, fill, line, w = 2) => {
  const px = -(ty - by), py = (tx - bx), Lp = Math.hypot(px, py) || 1;
  const r = Math.hypot(tx - bx, ty - by) * 0.3, ux = px / Lp * r, uy = py / Lp * r;
  const mx = (bx + tx) / 2, my = (by + ty) / 2;
  return `<path d="M${bx} ${by} Q${(mx + ux).toFixed(1)} ${(my + uy).toFixed(1)} ${tx} ${ty} Q${(mx - ux).toFixed(1)} ${(my - uy).toFixed(1)} ${bx} ${by} Z" fill="${fill}" stroke="${line}" stroke-width="${w}" stroke-linejoin="round"/><path d="M${bx} ${by} L${tx} ${ty}" stroke="${line}" stroke-width="${(w * 0.5).toFixed(1)}" opacity=".35"/>`;
};

export const ART_PLANTS = {
  // ── Sunflower Sprite — bloom-headed sprite: radiating petals ring a smiling face-disc, leafy stem body
  sunflowersprite: (c) => { const B = belly(c), P = tint(c.body, .4); return `
    ${floorShadow(60, 112, 24)}
    <g class="breathe">
      ${tube("M60 94 L60 66", c.body, c.line, 7)}
      ${leaf(56, 84, 38, 90, c.shade, c.line, 2.2)}
      ${leaf(64, 84, 82, 90, c.shade, c.line, 2.2)}
      <ellipse cx="60" cy="94" rx="15" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="97" rx="9" ry="6" fill="${B}"/>
    </g>
    <g class="head-tilt">
      ${Array.from({ length: 12 }, (_, i) => { const a = i * 30 * Math.PI / 180; return leaf(60 + 15 * Math.cos(a), 48 + 15 * Math.sin(a), 60 + 28 * Math.cos(a), 48 + 28 * Math.sin(a), P, c.line, 1.8); }).join("")}
      <circle cx="60" cy="48" r="17" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <circle cx="60" cy="48" r="12" fill="${B}"/>
      ${ceye(53, 46, 4)}${ceye(67, 46, 4)}
      <path d="M60 50 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      ${smile(60, 53, 3, INK)}
    </g>`; },

  // ── Cactus Beast — tall saguaro cactus, two arms hooking upward, ribs & spikes, a friendly face
  cactusbeast: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M48 80 Q28 80 28 60 Q28 51 36 51 Q43 52 43 62 Q43 74 48 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M72 80 Q92 80 92 60 Q92 51 84 51 Q77 52 77 62 Q77 74 72 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[[31, 66], [31, 58], [89, 66], [89, 58]].map(([x, y]) => `<path d="M${x} ${y} l-3 -1 M${x} ${y} l-3 2" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M46 100 Q42 42 60 40 Q78 42 74 100 Q60 106 46 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 50 Q50 74 53 96 M60 48 Q60 74 60 98 M68 50 Q70 74 67 96" fill="none" stroke="${D}" stroke-width="1.8" opacity=".5"/>
      <ellipse cx="60" cy="82" rx="13" ry="16" fill="${B}"/>
      ${[[52, 58], [60, 56], [68, 58], [50, 94], [70, 94], [60, 96]].map(([x, y]) => `<path d="M${x} ${y} l-2.5 -3.5 M${x} ${y} l2.5 -3.5" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>`).join("")}
      ${ceye(53, 72, 4)}${ceye(67, 72, 4)}
      <path d="M60 76 l-2 2.4 h4 Z" fill="${INK}"/>
      ${smile(60, 79, 3, INK)}
    </g>`; },

  // ── Toadstool Imp — pale stubby imp under a big spotted mushroom cap, rosy cheeks, tiny arms & feet
  toadstoolimp: (c) => { const B = belly(c), P = tint(c.body, .45); return `
    ${floorShadow(60, 112, 24)}
    <g class="breathe">
      <path d="M46 66 Q44 92 50 100 Q60 106 70 100 Q76 92 74 66 Z" fill="${B}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${tube("M48 80 Q38 84 38 94", B, c.line, 5)}
      ${tube("M72 80 Q82 84 82 94", B, c.line, 5)}
      <ellipse cx="52" cy="102" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="68" cy="102" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      ${ceye(53, 80, 3.8)}${ceye(67, 80, 3.8)}
      ${smile(60, 86, 2.8, INK)}
      <circle cx="47" cy="87" r="2.6" fill="${P}" opacity=".55"/><circle cx="73" cy="87" r="2.6" fill="${P}" opacity=".55"/>
    </g>
    <g class="head-tilt">
      <path d="M26 58 Q30 26 60 26 Q90 26 94 58 Q80 66 60 66 Q40 66 26 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M32 54 Q60 62 88 54" fill="none" stroke="${deepen(c.body, .15)}" stroke-width="2" opacity=".4"/>
      <circle cx="46" cy="42" r="5.5" fill="${P}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="65" cy="38" r="6.5" fill="${P}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="79" cy="50" r="4" fill="${P}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="36" cy="52" r="3.5" fill="${P}" stroke="${c.line}" stroke-width="1.4"/>
    </g>`; },

  // ── Venus Flytrap — snapping trap-head on a green stalk, interlocking teeth, red maw, eyes on the upper lobe
  venusflytrap: (c) => { const B = belly(c), R = tint(c.body, .3); return `
    ${floorShadow(60, 112, 24)}
    <g class="breathe">
      ${leaf(56, 100, 32, 96, c.shade, c.line, 2.4)}
      ${leaf(64, 100, 88, 96, c.shade, c.line, 2.4)}
      ${tube("M60 100 Q58 84 60 70", c.body, c.line, 9)}
    </g>
    <g class="head-tilt">
      <path d="M34 66 Q34 82 60 84 Q86 82 86 66 Q70 72 60 72 Q50 72 34 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 66 Q34 44 60 44 Q86 44 86 66 Q70 60 60 60 Q50 60 34 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 66 Q60 60 80 66 Q60 74 40 66 Z" fill="${R}" opacity=".85"/>
      ${Array.from({ length: 7 }, (_, i) => { const x = 41 + i * 6.3; return `<path d="M${x} 60 l1.4 6 l2.8 -6 Z" fill="${B}" stroke="${c.line}" stroke-width="0.8" stroke-linejoin="round"/>`; }).join("")}
      ${Array.from({ length: 7 }, (_, i) => { const x = 41 + i * 6.3; return `<path d="M${x} 72 l1.4 -6 l2.8 6 Z" fill="${B}" stroke="${c.line}" stroke-width="0.8" stroke-linejoin="round"/>`; }).join("")}
      ${ceye(52, 54, 3.8)}${ceye(68, 54, 3.8)}
    </g>`; },

  // ── Pitcher Plant — upright pitcher jug body with a hinged lid, veined rim, curious face
  pitcherplant: (c) => { const B = belly(c), D = deepen(c.body, .16), R = tint(c.body, .35); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M50 42 Q60 24 80 30 Q76 44 60 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${leaf(60, 100, 90, 104, c.shade, c.line, 2.4)}
      <path d="M42 48 Q40 42 47 43 Q60 47 73 43 Q80 42 78 48 Q84 74 74 96 Q60 106 46 96 Q36 74 42 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M45 47 Q60 53 75 47" fill="none" stroke="${R}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="60" cy="76" rx="15" ry="18" fill="${B}"/>
      <path d="M52 56 Q50 78 54 94 M68 56 Q70 78 66 94" fill="none" stroke="${D}" stroke-width="1.6" opacity=".45"/>
      ${ceye(53, 70, 4)}${ceye(67, 70, 4)}
      <path d="M60 74 l-2 2.4 h4 Z" fill="${INK}"/>
      ${smile(60, 77, 3, INK)}
    </g>`; },

  // ── Moss Golem — chunky boulder body, cracks, rocky arms, tufts of moss growing over the top
  mossgolem: (c) => { const B = belly(c), D = deepen(c.body, .22), M = tint(c.body, .2); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M34 66 L22 70 L20 86 L34 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M86 66 L98 70 L100 86 L86 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 60 L54 54 L86 60 L88 92 Q88 100 78 100 L42 100 Q32 100 32 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 66 L54 74 L48 82 M72 66 L68 76 L74 84" fill="none" stroke="${D}" stroke-width="1.6" opacity=".5"/>
      <ellipse cx="60" cy="82" rx="16" ry="12" fill="${B}"/>
      ${ceye(52, 76, 4)}${ceye(68, 76, 4)}
      <path d="M60 80 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 83, 3, INK)}
      ${pom(40, 58, 7, c.shade, c.line, 7, 2)}
      ${pom(52, 54, 7, M, c.line, 7, 2)}
      ${pom(64, 53, 7, c.shade, c.line, 7, 2)}
      ${pom(76, 57, 7, M, c.line, 7, 2)}
    </g>`; },

  // ── Vine Serpent — leafy green snake coiled at the base, rearing head with a leaf hood, forked sprout tongue
  vineserpent: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 28)}
    <g class="breathe">
      <ellipse cx="60" cy="96" rx="30" ry="12" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="91" rx="22" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${leaf(44, 92, 24, 86, c.shade, c.line, 1.8)}
      ${leaf(76, 92, 96, 86, c.shade, c.line, 1.8)}
      ${tube("M60 88 Q46 76 60 64", c.body, c.line, 14)}
      ${leaf(48, 50, 28, 40, c.shade, c.line, 2.2)}
      ${leaf(72, 50, 92, 40, c.shade, c.line, 2.2)}
      ${leaf(54, 44, 44, 26, c.shade, c.line, 2.2)}
      ${leaf(66, 44, 76, 26, c.shade, c.line, 2.2)}
      <path d="M42 54 Q42 38 60 38 Q78 38 78 54 Q78 66 60 68 Q42 66 42 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="56" rx="12" ry="9" fill="${B}"/>
      ${ceye(53, 52, 4)}${ceye(67, 52, 4)}
      <path d="M60 62 v5 M60 67 l-3 3 M60 67 l3 3" fill="none" stroke="${D}" stroke-width="1.8" stroke-linecap="round"/>
    </g>`; },

  // ── Bamboo Sprite — segmented bamboo stalk body, ring joints, leaf-sprig arms & a leafy crown
  bamboosprite: (c) => { const B = belly(c), D = deepen(c.body, .2); return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      ${leaf(58, 42, 36, 24, c.shade, c.line, 2)}
      ${leaf(60, 40, 60, 18, c.shade, c.line, 2)}
      ${leaf(62, 42, 84, 24, c.shade, c.line, 2)}
    </g>
    <g class="breathe">
      <path d="M46 44 Q46 40 60 40 Q74 40 74 44 L74 98 Q74 104 60 104 Q46 104 46 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 62 Q60 68 74 62 M46 82 Q60 88 74 82" fill="none" stroke="${D}" stroke-width="2.6"/>
      ${leaf(46, 68, 26, 62, c.shade, c.line, 2)}
      ${leaf(74, 68, 94, 62, c.shade, c.line, 2)}
      <ellipse cx="60" cy="52" rx="10" ry="7" fill="${B}"/>
      ${ceye(54, 50, 3.8)}${ceye(66, 50, 3.8)}
      <path d="M60 54 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 57, 2.6, INK)}
    </g>`; },

  // ── Lotus Spirit — floating lotus bloom, two rings of petals, serene face in the receptacle, lily pad below (float)
  lotusspirit: (c) => { const B = belly(c), P = tint(c.body, .42), P2 = tint(c.body, .22); return `
    ${floorShadow(60, 116, 20)}
    <g class="breathe">
      ${Array.from({ length: 5 }, (_, i) => { const a = (-90 + (i - 2) * 33) * Math.PI / 180; return leaf(60 + 8 * Math.cos(a), 64 + 8 * Math.sin(a), 60 + 40 * Math.cos(a), 64 + 40 * Math.sin(a), P2, c.line, 2.4); }).join("")}
      ${Array.from({ length: 4 }, (_, i) => { const a = (-90 + (i - 1.5) * 27) * Math.PI / 180; return leaf(60 + 6 * Math.cos(a), 66 + 6 * Math.sin(a), 60 + 30 * Math.cos(a), 66 + 30 * Math.sin(a), P, c.line, 2.4); }).join("")}
      <path d="M44 66 Q44 54 60 54 Q76 54 76 66 Q76 78 60 80 Q44 78 44 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="65" rx="12" ry="9" fill="${B}"/>
      ${ceye(53, 63, 3.8)}${ceye(67, 63, 3.8)}
      ${smile(60, 69, 3, INK)}
      <path d="M28 88 Q60 80 92 88 Q60 98 28 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 88 L76 84 M60 88 L46 84" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
    </g>`; },

  // ── Fern Fawn — dainty fawn, fern-frond antlers, big soft ears, dappled spots, slender hooved legs
  fernfawn: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${[[-16, -24], [-4, -30], [8, -25]].map(([dx, dy]) => leaf(52, 44, 52 + dx, 44 + dy, c.shade, c.line, 2)).join("")}
      ${[[16, -24], [4, -30], [-8, -25]].map(([dx, dy]) => leaf(68, 44, 68 + dx, 44 + dy, c.shade, c.line, 2)).join("")}
    </g>
    <g class="breathe">
      <path d="M42 96 Q38 68 60 66 Q82 68 78 96 Q60 104 42 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="46" y="92" width="8" height="16" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="66" y="92" width="8" height="16" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="45.5" y="105" width="9" height="4" rx="1.5" fill="${c.line}"/>
      <rect x="65.5" y="105" width="9" height="4" rx="1.5" fill="${c.line}"/>
      <ellipse cx="60" cy="86" rx="14" ry="11" fill="${B}"/>
      <circle cx="49" cy="80" r="2" fill="${B}"/><circle cx="71" cy="80" r="2" fill="${B}"/><circle cx="60" cy="76" r="2" fill="${B}"/>
    </g>
    <g class="head-tilt">
      <path d="M44 52 Q34 46 33 55 Q37 60 46 57 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M76 52 Q86 46 87 55 Q83 60 74 57 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 54 Q44 40 60 40 Q76 40 76 54 Q76 66 68 70 L68 74 Q60 78 52 74 L52 70 Q44 66 44 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="67" rx="8" ry="6" fill="${B}"/>
      <path d="M60 65 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      ${ceye(52, 54, 4)}${ceye(68, 54, 4)}
    </g>`; },

  // ── Acorn Critter — round acorn nut body with a crosshatched cap & stem, little peg legs, happy face (t1)
  acorncritter: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 22)}
    <g class="breathe">
      ${tube("M52 96 L50 106", c.body, c.line, 5)}${tube("M68 96 L70 106", c.body, c.line, 5)}
      <path d="M38 62 Q38 100 60 104 Q82 100 82 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="15" ry="14" fill="${B}"/>
      ${ceye(52, 78, 4)}${ceye(68, 78, 4)}
      <path d="M60 82 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 85, 3, INK)}
    </g>
    <g class="head-tilt">
      <path d="M34 62 Q34 42 60 42 Q86 42 86 62 Q60 70 34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 52 h40 M38 58 h44" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      ${[42, 50, 58, 66, 74, 82].map(x => `<path d="M${x} 46 v14" stroke="${c.line}" stroke-width="1" opacity=".35"/>`).join("")}
      ${tube("M60 44 L60 33", c.shade, c.line, 5)}
    </g>`; },

  // ── Pinecone Critter — teardrop pinecone with staggered rows of woody scales, little feet, peeking face (t1)
  pineconecritter: (c) => { const B = belly(c), S = tint(c.body, .16); return `
    ${floorShadow(60, 112, 22)}
    <g class="breathe">
      <ellipse cx="52" cy="104" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="68" cy="104" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 34 Q40 42 38 72 Q38 98 60 102 Q82 98 82 72 Q80 42 60 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[46, 58, 70, 84].map((y, row) => Array.from({ length: 5 }, (_, i) => { const x = 44 + i * 8 - (row % 2) * 4; return `<path d="M${x} ${y} Q${x + 5} ${y + 1} ${x + 4.5} ${y + 8} Q${x} ${y + 10} ${x - 4.5} ${y + 8} Q${x - 5} ${y + 1} ${x} ${y} Z" fill="${row % 2 ? S : c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`; }).join("")).join("")}
      <ellipse cx="60" cy="70" rx="13" ry="11" fill="${B}"/>
      ${ceye(53, 68, 3.8)}${ceye(67, 68, 3.8)}
      <path d="M60 72 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 75, 2.8, INK)}
    </g>`; },

  // ── Berry Sprite — cluster of round berries, one big face-berry up front with a glossy sheen, leafy sprig on top (t1)
  berrysprite: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M60 48 L60 40", c.shade, c.line, 4)}
      ${leaf(58, 42, 42, 30, c.shade, c.line, 2)}
      ${leaf(62, 42, 78, 30, c.shade, c.line, 2)}
    </g>
    <g class="breathe">
      ${[[46, 60], [74, 60], [40, 80], [80, 80], [52, 94], [68, 94]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="12" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>`).join("")}
      <circle cx="60" cy="76" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="52" cy="68" rx="5" ry="4" fill="${B}" opacity=".6"/>
      ${ceye(53, 74, 4)}${ceye(67, 74, 4)}
      <path d="M60 78 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 81, 3, INK)}
    </g>`; },

  // ── Leaf Fairy — chibi sprite with two leaf wings each side, a leafy hair-crown, rosy cheeks (float)
  leaffairy: (c) => { const B = belly(c); const wing = `<g class="tail-wag">${leaf(58, 58, 30, 44, c.shade, c.line, 2.4)}${leaf(58, 66, 32, 82, c.shade, c.line, 2.4)}</g>`; return `
    ${floorShadow(60, 114, 18)}
    ${wing}
    ${mirror(wing)}
    <g class="breathe">
      <path d="M60 58 Q52 60 52 72 Q52 84 60 86 Q68 84 68 72 Q68 60 60 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${tube("M55 84 Q54 92 56 98", c.body, c.line, 4)}${tube("M65 84 Q66 92 64 98", c.body, c.line, 4)}
      <circle cx="60" cy="42" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      ${leaf(52, 30, 40, 20, c.shade, c.line, 2)}${leaf(60, 28, 60, 15, c.shade, c.line, 2)}${leaf(68, 30, 80, 20, c.shade, c.line, 2)}
      <ellipse cx="60" cy="48" rx="11" ry="7" fill="${B}"/>
      ${ceye(53, 44, 4.2)}${ceye(67, 44, 4.2)}
      <path d="M60 49 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 52, 3, INK)}
      <circle cx="49" cy="50" r="2.2" fill="${tint(c.body, .4)}" opacity=".5"/><circle cx="71" cy="50" r="2.2" fill="${tint(c.body, .4)}" opacity=".5"/>
    </g>`; },

  // ── Bloom Bird — round chibi bird crowned with a flower of petals, petal fan tail, folded wing, twig legs
  bloombird: (c) => { const B = belly(c), P = tint(c.body, .32); return `
    ${floorShadow(60, 110, 22)}
    <g class="tail-wag">
      ${[[76, 78, 98, 70], [78, 84, 100, 86], [76, 90, 98, 100]].map(([bx, by, tx, ty]) => leaf(bx, by, tx, ty, c.shade, c.line, 2.2)).join("")}
    </g>
    <g class="breathe">
      <path d="M40 78 Q38 52 60 50 Q82 52 80 78 Q80 96 60 98 Q40 96 40 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M66 62 Q80 62 78 82 Q70 86 64 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="55" cy="80" rx="11" ry="12" fill="${B}"/>
      <path d="M54 96 l0 8 M54 104 l-4 3 M54 104 l4 3 M66 96 l0 8 M66 104 l-4 3 M66 104 l4 3" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${ceye(52, 70, 4)}${ceye(66, 70, 4)}
      <path d="M59 74 l-6 3 l6 3 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${Array.from({ length: 6 }, (_, i) => { const a = i * 60 * Math.PI / 180; return leaf(60 + 4 * Math.cos(a), 50 + 4 * Math.sin(a), 60 + 15 * Math.cos(a), 50 + 15 * Math.sin(a), P, c.line, 1.6); }).join("")}
      <circle cx="60" cy="50" r="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>
    </g>`; },

  // ── Spore Puff — round dandelion puffball, radiating seed-tufts, floating on a slim stem (float, t1)
  sporepuff: (c) => { const B = belly(c), T = tint(c.body, .5); return `
    ${floorShadow(60, 116, 18)}
    <g class="tail-wag">
      ${tube("M60 78 Q60 96 58 106", c.body, c.line, 5)}
    </g>
    <g class="breathe">
      ${Array.from({ length: 16 }, (_, i) => { const a = i * 22.5 * Math.PI / 180; const x2 = 60 + 32 * Math.cos(a), y2 = 58 + 32 * Math.sin(a); return `<path d="M60 58 L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${c.shade}" stroke-width="1.3" opacity=".7"/><circle cx="${x2.toFixed(1)}" cy="${y2.toFixed(1)}" r="2.1" fill="${T}"/>`; }).join("")}
      ${pom(60, 58, 22, c.body, c.line, 14, 2.6)}
      <ellipse cx="60" cy="64" rx="12" ry="9" fill="${B}"/>
      ${ceye(53, 56, 4)}${ceye(67, 56, 4)}
      <path d="M60 60 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 63, 3, INK)}
    </g>`; },

  // ── Ivy Wisp — floating vine-wisp, curling teardrop body sprouting leaves, trailing leafy tendril tail (float)
  ivywisp: (c) => { const B = belly(c); return `
    ${floorShadow(60, 116, 18)}
    <ellipse cx="60" cy="58" rx="26" ry="32" fill="${tint(c.body, .5)}" opacity=".14"/>
    <g class="tail-wag">
      ${tube("M60 84 Q52 98 60 108 Q67 100 63 92", c.body, c.line, 6)}
      ${leaf(55, 99, 43, 104, c.shade, c.line, 1.8)}${leaf(65, 99, 77, 105, c.shade, c.line, 1.8)}
    </g>
    <g class="breathe">
      <path d="M60 26 Q80 46 76 68 Q74 86 60 88 Q46 86 44 68 Q40 46 60 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${leaf(47, 52, 32, 46, c.shade, c.line, 1.8)}${leaf(73, 52, 88, 46, c.shade, c.line, 1.8)}
      ${leaf(56, 30, 48, 18, c.shade, c.line, 1.8)}${leaf(64, 30, 72, 18, c.shade, c.line, 1.8)}
      <path d="M60 44 Q70 56 67 70 Q64 80 60 82 Q56 80 53 70 Q50 56 60 44 Z" fill="${B}"/>
      ${ceye(53, 60, 4)}${ceye(67, 60, 4)}
      <path d="M60 64 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 67, 3, INK)}
    </g>`; },

  // ── Root Golem — hulking gnarled-root construct, knotted trunk, root arms & splayed root legs, knothole face
  rootgolem: (c) => { const B = belly(c), D = deepen(c.body, .22); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M40 68 Q24 66 20 80 Q18 88 24 90", c.body, c.line, 7)}
      ${tube("M80 68 Q96 66 100 80 Q102 88 96 90", c.body, c.line, 7)}
    </g>
    <g class="breathe">
      ${tube("M50 96 Q46 106 38 110", c.body, c.line, 7)}${tube("M70 96 Q74 106 82 110", c.body, c.line, 7)}${tube("M60 98 L60 110", c.body, c.line, 7)}
      <path d="M42 56 Q40 46 52 46 Q60 50 68 46 Q80 46 78 58 Q84 78 78 96 Q70 104 60 100 Q50 104 42 96 Q36 78 42 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 60 Q56 70 50 84 M72 60 Q66 72 72 86 M60 54 Q58 74 60 92" fill="none" stroke="${D}" stroke-width="1.8" opacity=".5"/>
      <ellipse cx="60" cy="74" rx="15" ry="15" fill="${B}"/>
      <path d="M48 66 q6 -3 11 0 M61 66 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${ceye(53, 72, 4)}${ceye(67, 72, 4)}
      <ellipse cx="60" cy="81" rx="5" ry="6" fill="${INK}"/>
      <ellipse cx="60" cy="80" rx="2.2" ry="2.8" fill="${B}"/>
    </g>`; },

  // ── Petal Moth — fuzzy moth with four flower-petal wings, feathered antennae, segmented body (float)
  petalmoth: (c) => { const B = belly(c), P = tint(c.body, .3); const wing = `${leaf(56, 52, 22, 36, P, c.line, 2.4)}${leaf(56, 64, 26, 82, P, c.line, 2.4)}`; return `
    ${floorShadow(60, 114, 20)}
    <g class="tail-wag">${wing}</g>
    ${mirror(`<g class="tail-wag">${wing}</g>`)}
    <g class="breathe">
      <path d="M60 66 Q52 70 52 84 Q52 96 60 98 Q68 96 68 84 Q68 70 60 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M53 76 q7 4 14 0 M53 86 q7 4 14 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      ${pom(60, 60, 11, c.body, c.line, 9, 2.4)}
      <path d="M54 46 Q46 36 44 27 M66 46 Q74 36 76 27" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${[0, 1, 2].map(i => `<path d="M${48 - i * 1.5} ${34 + i * 3.5} l-4 -1 M${72 + i * 1.5} ${34 + i * 3.5} l4 -1" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round"/>`).join("")}
      <ellipse cx="60" cy="58" rx="8" ry="6" fill="${B}"/>
      ${ceye(54, 57, 3.6)}${ceye(66, 57, 3.6)}
      ${smile(60, 60, 2.6, INK)}
    </g>`; },

  // ── Seed Pod — plump seed pod body, seam down the middle, a fresh two-leaf sprout on top, peg feet (t1)
  seedpod: (c) => { const B = belly(c), D = deepen(c.body, .16); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      ${tube("M60 44 Q60 34 60 30", c.shade, c.line, 4)}
      ${leaf(60, 34, 46, 24, c.shade, c.line, 2)}${leaf(60, 34, 74, 24, c.shade, c.line, 2)}
    </g>
    <g class="breathe">
      <ellipse cx="52" cy="102" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="68" cy="102" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 42 Q40 48 40 74 Q40 98 60 100 Q80 98 80 74 Q80 48 60 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 46 Q66 74 60 98" fill="none" stroke="${D}" stroke-width="1.8" opacity=".5"/>
      <ellipse cx="55" cy="74" rx="13" ry="15" fill="${B}"/>
      ${ceye(52, 72, 4)}${ceye(68, 72, 4)}
      <path d="M60 76 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 79, 3, INK)}
    </g>`; },
};

export const ROSTER_PLANTS = [
  { n: "Sunflower Sprite", e: "🌸", tier: 2, float: false },
  { n: "Cactus Beast",     e: "🌱", tier: 2, float: false },
  { n: "Toadstool Imp",    e: "🍄", tier: 2, float: false },
  { n: "Venus Flytrap",    e: "🌱", tier: 3, float: false },
  { n: "Pitcher Plant",    e: "🌱", tier: 2, float: false },
  { n: "Moss Golem",       e: "🌱", tier: 3, float: false },
  { n: "Vine Serpent",     e: "🌱", tier: 3, float: false },
  { n: "Bamboo Sprite",    e: "🌱", tier: 2, float: false },
  { n: "Lotus Spirit",     e: "🌸", tier: 3, float: true },
  { n: "Fern Fawn",        e: "🌱", tier: 2, float: false },
  { n: "Acorn Critter",    e: "🌱", tier: 1, float: false },
  { n: "Pinecone Critter", e: "🌱", tier: 1, float: false },
  { n: "Berry Sprite",     e: "🌸", tier: 1, float: false },
  { n: "Leaf Fairy",       e: "🌸", tier: 2, float: true },
  { n: "Bloom Bird",       e: "🌸", tier: 2, float: false },
  { n: "Spore Puff",       e: "🌱", tier: 1, float: true },
  { n: "Ivy Wisp",         e: "🌱", tier: 2, float: true },
  { n: "Root Golem",       e: "🌱", tier: 3, float: false },
  { n: "Petal Moth",       e: "🌸", tier: 2, float: true },
  { n: "Seed Pod",         e: "🌱", tier: 1, float: false },
];
