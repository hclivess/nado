// frogs2.js — BESPOKE hand-drawn SVG art for the FROGS & TOADS batch (NADO Pets).
// HOUSE STYLE: ONE continuous body+head silhouette (c.body fill, c.line outline, sw 3.2), legs TUCKED
// and overlapping the body (nothing floats), two-tone shading (belly + shade), big cute eyes, grounded
// with floorShadow. viewBox 0 0 120 120, animal centred ~(60,64), within x,y ∈ [8,114]. float:false —
// all frogs sit front-facing. Colours come from `c` (recoloured per pet at hatch); a FEW fixed accents
// only for iconic bright-frog features (red eyes / orange feet / blue flanks / fire belly).
// Does NOT duplicate reptiles.js frog / treefrog / toad.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// iconic fixed accents (used sparingly, per task spec)
const RED = "#e0524a", ORANGE = "#f2a03b", BLUE = "#5187c7", GOLD = "#f2c94c", CREAM = "#fbf6ee";

// ── shared silhouette + part builders (each species still composes its own look) ─────────────
// wide two-bump squat frog: body+head+eye-humps as ONE closed path
const squat = (c, { w = 36, eg = 15, ey = 40, by = 104 } = {}) => {
  const L = 60 - w, R = 60 + w, bt = ey - 9;
  return `<path d="M${L} ${by - 8}
    C${L - 3} ${by - 32} ${L + 1} ${by - 50} ${52 - eg} ${bt + 10}
    C${50 - eg} ${bt - 6} ${64 - eg} ${bt - 8} ${64 - eg} ${bt + 9}
    Q60 ${ey + 5} ${56 + eg} ${bt + 9}
    C${56 + eg} ${bt - 8} ${70 + eg} ${bt - 6} ${68 + eg} ${bt + 10}
    C${R - 1} ${by - 50} ${R + 3} ${by - 32} ${R} ${by - 8}
    Q60 ${by + 6} ${L} ${by - 8} Z"
    fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
};
// slim tall tree-frog torso (teardrop); eyes ride on separate domes on top
const treeTorso = (c, { w = 25, ty = 56, by = 102 } = {}) =>
  `<path d="M${60 - w} ${by - 6} C${60 - w - 5} ${by - 30} ${60 - w + 1} ${ty + 2} 60 ${ty}
    C${60 + w - 1} ${ty + 2} ${60 + w + 5} ${by - 30} ${60 + w} ${by - 6}
    Q60 ${by + 6} ${60 - w} ${by - 6} Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
// eye dome (raised protruding eye base for tree frogs)
const dome = (c, x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>`;
// webbed hind foot (palm + fan of toe tips), rooted up into the body
const web = (cx, cy, c, s = 1) => {
  const toes = [-10, -4, 2, 8].map((k, i) =>
    `<circle cx="${(cx + k * s).toFixed(1)}" cy="${(cy + 9 + (i === 0 || i === 3 ? 2.5 : 0)).toFixed(1)}" r="2.7" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`).join("");
  return `<ellipse cx="${cx}" cy="${cy + 3}" rx="10" ry="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>${toes}`;
};
// tiny front hand (three finger dots on a stub)
const hand = (cx, cy, c, s = 1) =>
  `<path d="M${cx} ${cy} q${3 * s} 6 ${1 * s} 9" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M${cx} ${cy} q${3 * s} 6 ${1 * s} 9" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>` +
  [-2.6, 0, 2.6].map((k) => `<circle cx="${(cx + s + k).toFixed(1)}" cy="${(cy + 11).toFixed(1)}" r="1.8" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("");
// splayed clinging limb ending in sticky toe discs (tree frogs)
const tlimb = (x, y, ex, ey, c) => {
  const dx = (ex - x) < 0 ? -1 : 1;
  const discs = [-1, 0, 1].map((k) => `<circle cx="${(ex + k * 4).toFixed(1)}" cy="${(ey + Math.abs(k) * 2).toFixed(1)}" r="3.1" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`).join("");
  return `<path d="M${x} ${y} Q${x + dx * 6} ${Math.max(y, ey) + 8} ${ex} ${ey}" fill="none" stroke="${c.line}" stroke-width="5.2" stroke-linecap="round"/>` +
    `<path d="M${x} ${y} Q${x + dx * 6} ${Math.max(y, ey) + 8} ${ex} ${ey}" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>${discs}`;
};
// scattered warts
const warts = (pts, c) => pts.map(([x, y, r = 2.3]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" opacity=".9"/>`).join("");
// dark blotch/spot
const spots = (pts, fill, c) => pts.map(([x, y, rx, ry = rx]) => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${fill}" stroke="${c.line}" stroke-width="1" opacity=".92"/>`).join("");
// wide frog grin
const grin = (c, { y = 66, w = 20, drop = 12 } = {}) =>
  `<path d="M${60 - w} ${y} Q60 ${y + drop} ${60 + w} ${y}" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>`;
// two nostril dots
const nost = (c, y = 54, g = 4) => `<circle cx="${60 - g}" cy="${y}" r="1.3" fill="${c.line}" opacity=".7"/><circle cx="${60 + g}" cy="${y}" r="1.3" fill="${c.line}" opacity=".7"/>`;

export const ART_FROGS2 = {
  // ── Red-eyed Tree Frog — slim, splayed clinging limbs w/ orange toe discs, blue flank bars, RED eyes
  redeyedtreefrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 27)}
    <g class="tail-wag">
      ${tlimb(38, 66, 22, 60, c)}${tlimb(82, 66, 98, 60, c)}
      ${tlimb(44, 84, 30, 98, c)}${tlimb(76, 84, 90, 98, c)}
    </g>
    <g class="breathe">
      ${treeTorso(c, { w: 24, ty: 58, by: 100 })}
      <ellipse cx="60" cy="82" rx="17" ry="12" fill="${B}"/>
      ${[[40, 74], [40, 84], [80, 74], [80, 84]].map(([x, y]) => `<path d="M${x} ${y} q${x < 60 ? -6 : 6} 3 ${x < 60 ? -7 : 7} 9" fill="none" stroke="${BLUE}" stroke-width="3.2" stroke-linecap="round" opacity=".92"/>`).join("")}
      ${grin(c, { y: 62, w: 16, drop: 9 })}${nost(c, 52, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 45, 46, 12)}${dome(c, 75, 46, 12)}
      <g class="blink"><ellipse cx="45" cy="46" rx="8.5" ry="9" fill="${RED}"/><ellipse cx="75" cy="46" rx="8.5" ry="9" fill="${RED}"/>
        <ellipse cx="45" cy="47" rx="3" ry="4.2" fill="${INK}"/><ellipse cx="75" cy="47" rx="3" ry="4.2" fill="${INK}"/>
        <circle cx="42.6" cy="43" r="1.7" fill="#fff"/><circle cx="72.6" cy="43" r="1.7" fill="#fff"/></g>
    </g>`; },

  // ── Tomato Frog — perfectly round chubby dome, tiny arms, small bright eyes, shy little smile
  tomatofrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 30)}
    <g class="tail-wag">${web(38, 100, c)}${web(82, 100, c)}</g>
    <g class="breathe">
      <path d="M22 78 C22 44 40 34 60 34 C80 34 98 44 98 78 C98 98 82 106 60 106 C38 106 22 98 22 78 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="26" ry="15" fill="${B}"/>
      <path d="M28 66 Q60 58 92 66" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
      ${grin(c, { y: 70, w: 15, drop: 8 })}${nost(c, 60, 3)}
      ${hand(48, 96, c, -1)}${hand(72, 96, c, 1)}
    </g>
    <g class="head-tilt">
      ${ceye(48, 56, 4.4)}${ceye(72, 56, 4.4)}
    </g>`; },

  // ── Pacman Frog — squat & wide, ENORMOUS gaping grin across the whole face, tiny eyes high on top
  pacmanfrog: (c) => { const B = belly(c); const M = deepen(c.body, 0.55); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">${web(34, 101, c)}${web(86, 101, c)}</g>
    <g class="breathe">
      ${squat(c, { w: 40, eg: 13, ey: 40, by: 104 })}
      <ellipse cx="60" cy="90" rx="30" ry="13" fill="${B}"/>
      ${spots([[38, 62, 6, 5], [82, 62, 6, 5], [60, 58, 5, 4]], c.shade, c)}
      <path d="M22 66 Q60 92 98 66 Q60 82 22 66 Z" fill="${M}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M28 68 Q60 84 92 68" fill="none" stroke="${CREAM}" stroke-width="2" opacity=".85"/>
      ${nost(c, 52, 5)}
      ${hand(46, 98, c, -1)}${hand(74, 98, c, 1)}
    </g>
    <g class="head-tilt">
      <circle cx="46" cy="40" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="74" cy="40" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${eyes(46, 74, 40, 3, eyeInk(c))}
    </g>`; },

  // ── Glass Frog — slim, pale TRANSLUCENT belly (heart shows through), forward-set big gold-ringed eyes
  glassfrog: (c) => { const B = tint(c.body, 0.82); return `
    ${floorShadow(60, 111, 26)}
    <g class="tail-wag">
      ${tlimb(40, 70, 26, 64, c)}${tlimb(80, 70, 94, 64, c)}
      ${tlimb(46, 86, 34, 98, c)}${tlimb(74, 86, 86, 98, c)}
    </g>
    <g class="breathe">
      ${treeTorso(c, { w: 23, ty: 54, by: 100 })}
      <ellipse cx="60" cy="82" rx="16" ry="13" fill="${B}" opacity=".95"/>
      <circle cx="60" cy="82" r="9" fill="${CREAM}" opacity=".55"/>
      <path d="M60 78 q-4 -4 -6 0 q0 4 6 7 q6 -3 6 -7 q-2 -4 -6 0 Z" fill="${RED}" opacity=".55"/>
      ${grin(c, { y: 58, w: 13, drop: 7 })}
    </g>
    <g class="head-tilt">
      ${dome(c, 50, 44, 11)}${dome(c, 70, 44, 11)}
      <g class="blink">
        <circle cx="50" cy="44" r="7.5" fill="${GOLD}"/><circle cx="70" cy="44" r="7.5" fill="${GOLD}"/>
        <circle cx="50" cy="45" r="3.6" fill="${INK}"/><circle cx="70" cy="45" r="3.6" fill="${INK}"/>
        <circle cx="48" cy="42" r="1.4" fill="#fff"/><circle cx="68" cy="42" r="1.4" fill="#fff"/></g>
    </g>`; },

  // ── Goliath Frog — GIANT, hugely muscular haunches, broad heavy body, powerful splayed legs, calm face
  goliathfrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 36)}
    <g class="tail-wag">
      ${web(26, 104, c, 1.2)}${web(94, 104, c, 1.2)}
    </g>
    <g class="breathe">
      <path d="M16 82 C16 74 22 66 34 62 C34 44 46 34 60 34 C74 34 86 44 86 62 C98 66 104 74 104 82
        C104 102 84 110 60 110 C36 110 16 102 16 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="32" ry="16" fill="${B}"/>
      <path d="M26 72 q10 -8 22 -6 M94 72 q-10 -8 -22 -6" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".55"/>
      ${grin(c, { y: 66, w: 22, drop: 12 })}${nost(c, 54, 4)}
      ${hand(44, 100, c, -1)}${hand(76, 100, c, 1)}
    </g>
    <g class="head-tilt">
      <circle cx="46" cy="50" r="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="74" cy="50" r="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${ceye(46, 50, 4.6)}${ceye(74, 50, 4.6)}
    </g>`; },

  // ── African Bullfrog — chunky wide, ridged dorsal skin folds, big grumpy down-mouth, heavy jowls
  africanbullfrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 33)}
    <g class="tail-wag">${web(32, 101, c, 1.1)}${web(88, 101, c, 1.1)}</g>
    <g class="breathe">
      ${squat(c, { w: 41, eg: 14, ey: 42, by: 104 })}
      <ellipse cx="60" cy="92" rx="30" ry="13" fill="${B}"/>
      ${[54, 68, 82].map((y) => `<path d="M30 ${y} Q60 ${y - 8} 90 ${y}" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".7"/>`).join("")}
      <path d="M34 70 Q60 82 86 70 Q60 76 34 70 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M40 72 Q60 66 80 72" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      ${nost(c, 56, 4)}
      ${hand(46, 98, c, -1)}${hand(74, 98, c, 1)}
    </g>
    <g class="head-tilt">
      <path d="M38 44 q8 -5 16 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M66 44 q8 -5 16 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${ceye(48, 46, 4.2)}${ceye(72, 46, 4.2)}
    </g>`; },

  // ── Darwin's Frog — leaf-mimic, slim, distinctive POINTY snout proboscis, angular slanted eyes
  darwinsfrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 24)}
    <g class="tail-wag">
      ${tlimb(42, 74, 30, 68, c)}${tlimb(78, 74, 90, 68, c)}
      ${web(46, 100, c, 0.9)}${web(74, 100, c, 0.9)}
    </g>
    <g class="breathe">
      <path d="M34 78 C34 58 44 48 60 48 C76 48 86 58 86 78 C86 96 74 104 60 104 C46 104 34 96 34 78 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="17" ry="12" fill="${B}"/>
      <path d="M60 52 L60 96" stroke="${c.shade}" stroke-width="2" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <path d="M44 52 Q52 40 60 34 Q68 40 76 52 Q60 64 44 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M56 34 Q60 24 64 34 L60 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${ceye(50, 52, 3.8)}${ceye(70, 52, 3.8)}
      ${grin(c, { y: 56, w: 8, drop: 4 })}
    </g>`; },

  // ── Surinam Toad — FLAT & angular, splayed limbs ending in STAR-tip toes, tiny dot eyes, wide flat head
  surinamtoad: (c) => { const B = belly(c); const star = (cx, cy, c) =>
    [0, 1, 2, 3].map((k) => `<path d="M${cx} ${cy} l${[-9, -3, 3, 9][k]} ${[10, 13, 13, 10][k]}" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M${cx} ${cy} l${[-9, -3, 3, 9][k]} ${[10, 13, 13, 10][k]}" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>` +
      `<path d="M${cx + [-9, -3, 3, 9][k]} ${cy + [10, 13, 13, 10][k]} l-1.6 -1.6 m1.6 1.6 l1.6 -1.6 m-1.6 1.6 l0 2.2" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>`).join("");
    return `
    ${floorShadow(60, 111, 34)}
    <g class="tail-wag">${star(30, 88, c)}${star(90, 88, c)}</g>
    <g class="breathe">
      <path d="M20 76 Q20 62 34 58 L44 46 Q60 42 76 46 L86 58 Q100 62 100 76 Q100 94 60 98 Q20 94 20 76 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M30 76 Q60 88 90 76" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
      <path d="M60 50 L60 92" stroke="${c.shade}" stroke-width="1.6" opacity=".4"/>
      ${warts([[40, 66], [80, 66], [50, 82], [70, 82], [60, 72]], c)}
      ${grin(c, { y: 62, w: 22, drop: 6 })}${nost(c, 52, 5)}
    </g>
    <g class="head-tilt">
      ${eyes(50, 70, 54, 2.4, eyeInk(c))}
    </g>`; },

  // ── Cane Toad — big warty dome, huge parotoid glands behind the eyes, dry hooded eyes, blunt grin
  canetoad: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">${web(34, 101, c)}${web(86, 101, c)}</g>
    <g class="breathe">
      ${squat(c, { w: 40, eg: 14, ey: 44, by: 104 })}
      <ellipse cx="60" cy="92" rx="29" ry="13" fill="${B}"/>
      <ellipse cx="40" cy="54" rx="9" ry="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(-16 40 54)"/>
      <ellipse cx="80" cy="54" rx="9" ry="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(16 80 54)"/>
      ${warts([[52, 74], [68, 74], [44, 84], [60, 86], [76, 84], [60, 68, 2], [34, 80], [86, 80]], c)}
      <path d="M40 72 Q60 80 80 72" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${nost(c, 58, 4)}
      ${hand(46, 98, c, -1)}${hand(74, 98, c, 1)}
    </g>
    <g class="head-tilt">
      <path d="M40 48 q8 -3 15 0 M65 48 q8 -3 15 0" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${eyes(48, 72, 50, 3.4, eyeInk(c))}
    </g>`; },

  // ── Wood Frog — slim, signature dark robber's MASK band through the eyes, pale lip line
  woodfrog: (c) => { const B = belly(c); const M = deepen(c.body, 0.5); return `
    ${floorShadow(60, 111, 26)}
    <g class="tail-wag">
      ${tlimb(40, 72, 28, 66, c)}${tlimb(80, 72, 92, 66, c)}
      ${web(46, 100, c, 0.9)}${web(74, 100, c, 0.9)}
    </g>
    <g class="breathe">
      ${squat(c, { w: 33, eg: 15, ey: 44, by: 102 })}
      <ellipse cx="60" cy="88" rx="22" ry="12" fill="${B}"/>
      <path d="M32 60 Q60 54 88 60" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M30 46 Q60 40 90 46 Q88 56 78 57 L42 57 Q32 56 30 46 Z" fill="${M}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M32 60 Q60 66 88 60" fill="none" stroke="${CREAM}" stroke-width="2" opacity=".7"/>
      ${ceye(46, 48, 4.2)}${ceye(74, 48, 4.2)}
      ${grin(c, { y: 64, w: 16, drop: 8 })}${nost(c, 58, 3)}
    </g>`; },

  // ── Leopard Frog — slim green frog covered in big bold rounded dark SPOTS with pale rings
  leopardfrog: (c) => { const B = belly(c); const S = deepen(c.body, 0.4); return `
    ${floorShadow(60, 111, 28)}
    <g class="tail-wag">
      ${tlimb(40, 74, 28, 68, c)}${tlimb(80, 74, 92, 68, c)}
      ${web(46, 101, c)}${web(74, 101, c)}
    </g>
    <g class="breathe">
      ${squat(c, { w: 35, eg: 15, ey: 44, by: 102 })}
      <ellipse cx="60" cy="88" rx="24" ry="12" fill="${B}"/>
      ${[[38, 72, 5], [54, 66, 5], [72, 68, 5], [84, 76, 4], [48, 82, 4.5], [66, 82, 4.5], [60, 74, 4]].map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r + 1.4}" fill="${tint(c.body, 0.5)}"/><circle cx="${x}" cy="${y}" r="${r}" fill="${S}"/>`).join("")}
      <path d="M30 54 q6 6 6 22 M90 54 q-6 6 -6 22" fill="none" stroke="${tint(c.body, 0.4)}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
      ${grin(c, { y: 64, w: 16, drop: 8 })}${nost(c, 58, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 47, 46, 8)}${dome(c, 73, 46, 8)}
      ${ceye(47, 46, 4.4)}${ceye(73, 46, 4.4)}
    </g>`; },

  // ── Gray Tree Frog — knobbly BUMPY textured skin, mottled patches, toe discs, big round eyes
  graytreefrog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 27)}
    <g class="tail-wag">
      ${tlimb(38, 68, 24, 62, c)}${tlimb(82, 68, 96, 62, c)}
      ${tlimb(46, 86, 34, 99, c)}${tlimb(74, 86, 86, 99, c)}
    </g>
    <g class="breathe">
      ${treeTorso(c, { w: 26, ty: 56, by: 100 })}
      <ellipse cx="60" cy="82" rx="17" ry="12" fill="${B}"/>
      ${spots([[42, 70, 7, 5], [76, 72, 6, 5], [60, 64, 6, 4]], c.shade, c)}
      ${warts([[50, 76], [70, 76], [60, 84], [44, 62], [78, 64], [38, 80], [82, 80]], c)}
      ${grin(c, { y: 60, w: 15, drop: 8 })}${nost(c, 52, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 46, 46, 11)}${dome(c, 74, 46, 11)}
      ${ceye(46, 46, 5.4)}${ceye(74, 46, 5.4)}
    </g>`; },

  // ── Spring Peeper — tiny slim frog with the signature dark X mark on its back, big shiny eyes
  springpeeper: (c) => { const B = belly(c); const X = deepen(c.body, 0.5); return `
    ${floorShadow(60, 111, 24)}
    <g class="tail-wag">
      ${tlimb(42, 72, 30, 66, c)}${tlimb(78, 72, 90, 66, c)}
      ${tlimb(48, 88, 38, 100, c)}${tlimb(72, 88, 82, 100, c)}
    </g>
    <g class="breathe">
      <path d="M36 80 C36 60 44 50 60 50 C76 50 84 60 84 80 C84 96 74 104 60 104 C46 104 36 96 36 80 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 67 L68 78 M68 67 L52 78" fill="none" stroke="${X}" stroke-width="3.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="88" rx="14" ry="9" fill="${B}"/>
      ${grin(c, { y: 62, w: 13, drop: 7 })}${nost(c, 54, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 48, 48, 9)}${dome(c, 72, 48, 9)}
      ${ceye(48, 48, 4.6)}${ceye(72, 48, 4.6)}
    </g>`; },

  // ── Mantella — small smooth poison-dart frog, bright body, contrasting dark limbs, bold eyes
  mantella: (c) => { const B = belly(c); const D = deepen(c.body, 0.55); return `
    ${floorShadow(60, 111, 25)}
    <g class="tail-wag">
      ${tlimb(40, 72, 28, 66, { ...c, body: D, shade: D })}${tlimb(80, 72, 92, 66, { ...c, body: D, shade: D })}
      ${web(46, 100, { ...c, body: D, shade: D }, 0.9)}${web(74, 100, { ...c, body: D, shade: D }, 0.9)}
    </g>
    <g class="breathe">
      <path d="M34 78 C34 58 44 48 60 48 C76 48 86 58 86 78 C86 96 74 103 60 103 C46 103 34 96 34 78 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="18" ry="12" fill="${B}"/>
      <path d="M36 62 Q60 56 84 62" fill="none" stroke="${tint(c.body, 0.4)}" stroke-width="2.4" opacity=".7"/>
      ${warts([[46, 74], [74, 74], [60, 80, 2]], c)}
      ${grin(c, { y: 62, w: 14, drop: 7 })}${nost(c, 54, 3)}
    </g>
    <g class="head-tilt">
      ${dome({ ...c, body: D }, 47, 48, 8)}${dome({ ...c, body: D }, 73, 48, 8)}
      <g class="blink"><circle cx="47" cy="48" r="4.4" fill="${GOLD}"/><circle cx="73" cy="48" r="4.4" fill="${GOLD}"/>
        <circle cx="47" cy="48" r="2.4" fill="${INK}"/><circle cx="73" cy="48" r="2.4" fill="${INK}"/>
        <circle cx="45.6" cy="46.6" r="1" fill="#fff"/><circle cx="71.6" cy="46.6" r="1" fill="#fff"/></g>
    </g>`; },

  // ── Reed Frog — very slim & elegant, long legs, a crisp lateral stripe down each flank, dainty face
  reedfrog: (c) => { const B = belly(c); const S = tint(c.body, 0.55); return `
    ${floorShadow(60, 111, 23)}
    <g class="tail-wag">
      ${tlimb(42, 70, 30, 62, c)}${tlimb(78, 70, 90, 62, c)}
      ${tlimb(48, 88, 40, 102, c)}${tlimb(72, 88, 80, 102, c)}
    </g>
    <g class="breathe">
      <path d="M40 82 C40 60 46 48 60 48 C74 48 80 60 80 82 C80 98 72 104 60 104 C48 104 40 98 40 82 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="14" ry="11" fill="${B}"/>
      <path d="M44 64 Q42 82 48 98" fill="none" stroke="${S}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M76 64 Q78 82 72 98" fill="none" stroke="${S}" stroke-width="3.4" stroke-linecap="round"/>
      ${grin(c, { y: 62, w: 12, drop: 7 })}${nost(c, 54, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 49, 48, 9)}${dome(c, 71, 48, 9)}
      ${ceye(49, 48, 4.8)}${ceye(71, 48, 4.8)}
    </g>`; },

  // ── Fire-bellied Toad — flattish warty body w/ dark mottling on top, bright fire-belly & feet flashes
  firebelliedtoad: (c) => { const B = belly(c); const M = deepen(c.body, 0.5); return `
    ${floorShadow(60, 111, 31)}
    <g class="tail-wag">
      ${tlimb(38, 74, 26, 68, c)}${tlimb(82, 74, 94, 68, c)}
      <ellipse cx="42" cy="102" rx="9" ry="6" fill="${ORANGE}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="78" cy="102" rx="9" ry="6" fill="${ORANGE}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="breathe">
      <path d="M22 76 Q22 60 38 56 Q46 46 60 46 Q74 46 82 56 Q98 60 98 76 Q98 96 60 100 Q22 96 22 76 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 90 Q60 98 80 90 Q60 94 40 90 Z" fill="${ORANGE}" opacity=".85"/>
      ${spots([[38, 66, 6, 4], [58, 60, 6, 4], [78, 66, 6, 4], [48, 76, 5, 3.5], [72, 76, 5, 3.5]], M, c)}
      ${warts([[46, 70], [60, 66], [74, 70], [54, 82], [66, 82]], c)}
      ${grin(c, { y: 68, w: 20, drop: 8 })}${nost(c, 56, 4)}
    </g>
    <g class="head-tilt">
      ${ceye(46, 52, 4)}${ceye(74, 52, 4)}
    </g>`; },

  // ── Waxy Monkey Frog — SITS UP upright, waxy pale skin, arms gripping down front, chill half-lidded eyes
  waxymonkeyfrog: (c) => { const B = tint(c.body, 0.4); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tlimb(40, 92, 30, 104, c)}${tlimb(80, 92, 90, 104, c)}
    </g>
    <g class="breathe">
      <path d="M38 96 C34 66 42 38 60 38 C78 38 86 66 82 96 C80 106 68 110 60 110 C52 110 40 106 38 96 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="17" ry="20" fill="${B}"/>
      <path d="M44 60 Q42 84 52 100" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M44 60 Q42 84 52 100" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
      <path d="M76 60 Q78 84 68 100" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M76 60 Q78 84 68 100" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
      ${[48, 60, 72].map((x) => `<circle cx="${x}" cy="102" r="2.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("")}
      ${grin(c, { y: 56, w: 13, drop: 6 })}${nost(c, 48, 3)}
    </g>
    <g class="head-tilt">
      <path d="M40 40 q8 -4 15 -1 M65 40 q8 -4 15 -1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${ceye(47, 42, 4)}${ceye(73, 42, 4)}
    </g>`; },

  // ── Clown Tree Frog — bold harlequin blotch pattern all over, toe discs, big cheerful round eyes
  clowntreefrog: (c) => { const B = belly(c); const S = deepen(c.body, 0.45), P = tint(c.body, 0.5); return `
    ${floorShadow(60, 111, 27)}
    <g class="tail-wag">
      ${tlimb(38, 68, 24, 62, c)}${tlimb(82, 68, 96, 62, c)}
      ${tlimb(46, 86, 34, 99, c)}${tlimb(74, 86, 86, 99, c)}
    </g>
    <g class="breathe">
      ${treeTorso(c, { w: 26, ty: 56, by: 100 })}
      <ellipse cx="60" cy="82" rx="17" ry="12" fill="${B}"/>
      <path d="M38 58 Q60 50 82 58 Q78 71 60 68 Q42 71 38 58 Z" fill="${S}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M46 80 Q60 74 74 80 Q68 92 60 92 Q52 92 46 80 Z" fill="${S}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="63" rx="4.5" ry="3" fill="${P}"/>
      ${spots([[48, 62, 2.4, 2], [72, 62, 2.4, 2]], P, c)}
      ${grin(c, { y: 60, w: 14, drop: 8 })}${nost(c, 52, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 46, 46, 11)}${dome(c, 74, 46, 11)}
      ${ceye(46, 46, 5.2)}${ceye(74, 46, 5.2)}
    </g>`; },

  // ── Marsh Frog — round streamlined swimmer, bold pale dorsal mid-stripe, small flank spots, wide eyes
  marshfrog: (c) => { const B = belly(c); const S = tint(c.body, 0.55); return `
    ${floorShadow(60, 111, 29)}
    <g class="tail-wag">
      ${tlimb(40, 74, 26, 66, c)}${tlimb(80, 74, 94, 66, c)}
      ${web(44, 101, c, 1)}${web(76, 101, c, 1)}
    </g>
    <g class="breathe">
      <path d="M30 80 C30 60 40 50 60 50 C80 50 90 60 90 80 C90 96 78 104 60 104 C42 104 30 96 30 80 Z"
        fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="21" ry="12" fill="${B}"/>
      <path d="M60 52 L60 100" stroke="${S}" stroke-width="4.5" stroke-linecap="round"/>
      ${spots([[42, 72, 3.5, 2.6], [78, 72, 3.5, 2.6], [48, 84, 3, 2.2], [72, 84, 3, 2.2]], c.shade, c)}
      ${grin(c, { y: 64, w: 15, drop: 8 })}${nost(c, 58, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 46, 47, 9)}${dome(c, 74, 47, 9)}
      ${ceye(46, 47, 4.6)}${ceye(74, 47, 4.6)}
    </g>`; },

  // ── Painted Frog — squat with irregular painted colour blotches (light + dark) scattered over the back
  paintedfrog: (c) => { const B = belly(c); const D = deepen(c.body, 0.42), P = tint(c.body, 0.55); return `
    ${floorShadow(60, 111, 29)}
    <g class="tail-wag">${web(34, 101, c)}${web(86, 101, c)}</g>
    <g class="breathe">
      ${squat(c, { w: 37, eg: 15, ey: 44, by: 103 })}
      <ellipse cx="60" cy="90" rx="25" ry="12" fill="${B}"/>
      <path d="M38 66 Q48 58 56 66 Q52 76 42 74 Q34 72 38 66 Z" fill="${D}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <path d="M74 68 Q84 60 88 70 Q84 80 76 78 Q70 74 74 68 Z" fill="${P}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <path d="M52 82 Q62 76 70 84 Q64 92 58 90 Q50 88 52 82 Z" fill="${D}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <ellipse cx="66" cy="59" rx="4" ry="3" fill="${P}"/>
      ${grin(c, { y: 66, w: 17, drop: 9 })}${nost(c, 56, 3)}
    </g>
    <g class="head-tilt">
      ${dome(c, 47, 46, 8)}${dome(c, 73, 46, 8)}
      ${ceye(47, 46, 4.2)}${ceye(73, 46, 4.2)}
    </g>`; },
};

export const ROSTER_FROGS2 = [
  { n: "Red-eyed Tree Frog", e: "🐸", tier: 2, float: false },
  { n: "Tomato Frog",        e: "🐸", tier: 2, float: false },
  { n: "Pacman Frog",        e: "🐸", tier: 2, float: false },
  { n: "Glass Frog",         e: "🐸", tier: 2, float: false },
  { n: "Goliath Frog",       e: "🐸", tier: 3, float: false },
  { n: "African Bullfrog",   e: "🐸", tier: 2, float: false },
  { n: "Darwin's Frog",      e: "🐸", tier: 2, float: false },
  { n: "Surinam Toad",       e: "🐸", tier: 2, float: false },
  { n: "Cane Toad",          e: "🐸", tier: 1, float: false },
  { n: "Wood Frog",          e: "🐸", tier: 1, float: false },
  { n: "Leopard Frog",       e: "🐸", tier: 1, float: false },
  { n: "Gray Tree Frog",     e: "🐸", tier: 1, float: false },
  { n: "Spring Peeper",      e: "🐸", tier: 1, float: false },
  { n: "Mantella",           e: "🐸", tier: 2, float: false },
  { n: "Reed Frog",          e: "🐸", tier: 1, float: false },
  { n: "Fire-bellied Toad",  e: "🐸", tier: 2, float: false },
  { n: "Waxy Monkey Frog",   e: "🐸", tier: 2, float: false },
  { n: "Clown Tree Frog",    e: "🐸", tier: 1, float: false },
  { n: "Marsh Frog",         e: "🐸", tier: 1, float: false },
  { n: "Painted Frog",       e: "🐸", tier: 1, float: false },
];
