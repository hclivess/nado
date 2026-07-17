// pets-art/raptors.js — BESPOKE hand-drawn SVG art for RAPTORS (birds of prey) — NADO Pets.
// HOUSE STYLE (see METHOD.md): ONE continuous body+head silhouette (c.body, thick round outline),
// two-tone shading (belly() breast + c.shade wing/back), a clean fierce/cute face, wings & talons
// tucked so NOTHING floats. Each value: (c) => "<svg inner markup>" for viewBox 0 0 120 120, bird
// perched & centered ~(60,62), within x,y ∈ [8,114]. Colours come from the coat object c
// (c.body main / c.shade accent / c.line outline). Hooked beaks, ceres, talons & bare skin are the
// only fixed warm accents (yellow #f2c94c / orange #e79a3a); everything else recolours from c.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk } from "../pets-draw.js";

const ACC = "#f2c94c";   // yellow: hooked beak, cere, talons, eye-ring
const ACC2 = "#e79a3a";  // darker warm: legs, bare facial skin, beak-hook underside
const WHT = "#fbf6ee";   // species-white: barn-owl / sea-eagle head, facial-disc highlight (not coat)

// ── shared silhouettes (perched, head merged into body — a single closed path) ──────────────
const BODC  = "M60 18 C46 18 41 30 43 42 C29 48 27 70 33 90 C38 104 50 106 60 106 C70 106 82 104 87 90 C93 70 91 48 77 42 C79 30 74 18 60 18 Z";           // compact hunched hawk
const BIGC  = "M60 15 C43 15 38 27 40 40 C24 45 21 68 28 91 C34 107 48 109 60 109 C72 109 86 107 92 91 C99 68 96 45 80 40 C82 27 77 15 60 15 Z";           // broad, powerful eagle
const SLIMC = "M60 20 C50 20 46 30 47 42 C38 48 36 70 41 92 C45 106 54 108 60 108 C66 108 75 106 79 92 C84 70 82 48 73 42 C74 30 70 20 60 20 Z";           // slim, long-winged
const OWLC  = "M60 14 C38 14 28 33 28 56 C28 84 41 106 60 106 C79 106 92 84 92 56 C92 33 82 14 60 14 Z";                                                  // round owl
const HUNCHC= "M60 24 C52 24 49 31 50 39 C36 41 28 57 30 79 C33 101 47 106 60 106 C73 106 87 101 90 79 C92 57 84 41 70 39 C71 31 68 24 60 24 Z";           // hunched, small-headed vulture

// ── shared parts ────────────────────────────────────────────────────────────────────────────
const body = (d, c, w = 3.2) => `<path d="${d}" fill="${c.body}" stroke="${c.line}" stroke-width="${w}" stroke-linejoin="round"/>`;
const breast = (B) => `<path d="M60 46 C50 46 44 58 46 76 C48 94 54 99 60 99 C66 99 72 94 74 76 C76 58 70 46 60 46 Z" fill="${B}"/>`;
const wings = (c) => { const w = `<path d="M42 50 Q31 71 38 92 Q45 73 47 55 Z" fill="${c.shade}"/>`; return w + mirror(w); };
const brow = (c) => { const b = `<path d="M44 30 Q52 30 58 34 L57 37 Q51 33 45 34 Z" fill="${c.shade}"/>`; return b + mirror(b); };
// heavy clenched raptor foot gripping at (x, y)
const foot = (x, y) => `<path d="M${x} ${y} l0 6 M${x - 5} ${y + 6} h10 M${x - 4} ${y + 6} l-2 5 M${x + 4} ${y + 6} l2 5 M${x} ${y + 6} l0 5" stroke="${ACC}" stroke-width="2.6" fill="none" stroke-linecap="round"/>`;
const talons = (xs, y) => xs.map((x) => foot(x, y)).join("");
// long scaly leg + gripping foot (long-legged raptors)
const legfoot = (x, yt, yb) => `<path d="M${x} ${yt} L${x} ${yb}" stroke="${ACC2}" stroke-width="3.2" stroke-linecap="round"/>${foot(x, yb)}`;
// fierce yellow raptor eye (dark pupil + catchlight, always visible on any coat)
const reye = (x, y, r = 4.6) => `<g class="blink"><circle cx="${x}" cy="${y}" r="${r}" fill="${ACC}" stroke="${INK}" stroke-width="1.1"/><circle cx="${x}" cy="${y}" r="${(r * 0.52).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.34).toFixed(1)}" r="${(r * 0.24).toFixed(1)}" fill="#fff"/></g>`;
// downward hooked beak centred at (x,y), scale s
const hookbeak = (x, y, s = 1) => `<path d="M${x - 4 * s} ${y} Q${x} ${y - 2.4 * s} ${x + 4 * s} ${y} Q${x + 3.2 * s} ${y + 5 * s} ${x + 1.4 * s} ${y + 7 * s} Q${x} ${y + 10.5 * s} ${x - 1.6 * s} ${y + 7 * s} Q${x - 3.2 * s} ${y + 5 * s} ${x - 4 * s} ${y} Z" fill="${ACC}" stroke="${INK}" stroke-width="1.5" stroke-linejoin="round"/><path d="M${x - 1.6 * s} ${y + 7 * s} Q${x} ${y + 10.5 * s} ${x + 1.4 * s} ${y + 7 * s} Q${x} ${y + 8.6 * s} ${x - 1.6 * s} ${y + 7 * s} Z" fill="${ACC2}"/><ellipse cx="${x + 2 * s}" cy="${y + 2 * s}" rx="${0.9 * s}" ry="${0.7 * s}" fill="${INK}" opacity=".55"/>`;
// pointed ear-tufts (owls) rooted in the crown
const tufts = (c, x = 42, root = 34, tip = 12) => { const t = `<path d="M${x} ${root} L${x - 6} ${tip} L${x + 10} ${root - 4} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M${x + 1} ${root - 2} L${x - 3} ${tip + 6} L${x + 6} ${root - 3} Z" fill="${c.shade}"/>`; return t + mirror(t); };
// round owl facial disc
const disc = (c, B) => `<path d="M60 32 C42 32 33 46 33 60 C33 78 45 90 60 90 C75 90 87 78 87 60 C87 46 78 32 60 32 Z" fill="${B}" stroke="${c.line}" stroke-width="1.4"/><path d="M60 35 V86" stroke="${c.shade}" stroke-width="1" opacity=".35"/>`;

export const ART_RAPTORS = {
  // Osprey — fish-hawk: white head with a bold dark eye-mask band, speckled necklace, hooked beak
  osprey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag"><path d="M47 96 Q44 112 54 110 L57 101 L60 110 L63 101 L66 110 Q76 112 73 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M50 101 h20 M52 106 h16" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      ${[[54, 60], [66, 60], [60, 68], [54, 74], [66, 74]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.5" fill="${c.shade}" opacity=".7"/>`).join("")}
      ${wings(c)}
      <path d="M60 19 C48 19 44 29 45 40 Q52 45 60 45 Q68 45 75 40 C76 29 72 19 60 19 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M45 31 Q60 34 75 31 L76 39 Q60 43 44 39 Z" fill="${c.shade}"/>
      ${reye(51, 35)}${reye(69, 35)}
      ${hookbeak(60, 44, 1)}
    </g>
    ${talons([50, 70], 99)}`; },

  // Kestrel — dainty falcon: blue-grey cap, rufous back, TWO black malar moustaches, spotted breast
  kestrel: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M52 94 Q49 112 60 110 Q71 112 68 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M54 106 h12" stroke="${c.line}" stroke-width="1.4" opacity=".5"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      ${[[53, 58], [67, 58], [60, 64], [53, 70], [67, 70], [60, 76]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.3" fill="${c.shade}" opacity=".65"/>`).join("")}
      ${wings(c)}
      <path d="M60 19 C47 19 43 30 45 41 Q52 45 60 45 Q68 45 75 41 C77 30 73 19 60 19 Z" fill="${c.shade}"/>
      ${reye(51, 34)}${reye(69, 34)}
      <path d="M53 39 L50 50 L55 49 Z" fill="${c.shade}"/><path d="M67 39 L70 50 L65 49 Z" fill="${c.shade}"/>
      ${hookbeak(60, 43, 0.86)}
    </g>
    ${talons([51, 69], 99)}`; },

  // Harrier — slim low-hunter: soft owl-like facial ruff, long body & tail, pale rump band
  harrier: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M52 96 Q49 114 60 112 Q71 114 68 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M53 101 h14 M54 107 h12" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      ${body(SLIMC, c)}
      ${breast(B)}
      ${[62, 72, 82].map((y) => `<path d="M50 ${y} q10 4 20 0" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".55"/>`).join("")}
      ${wings(c)}
      <path d="M60 22 C49 22 44 33 46 44 Q53 50 60 50 Q67 50 74 44 C76 33 71 22 60 22 Z" fill="${B}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M46 44 Q60 49 74 44" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".6"/>
      ${reye(52, 36)}${reye(68, 36)}
      ${hookbeak(60, 45, 0.82)}
    </g>
    ${talons([52, 68], 100)}`; },

  // Buzzard — robust, broad-shouldered: dark hood, pale streaked breast with a dark belly-band
  buzzard: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 29)}
    <g class="tail-wag"><path d="M46 94 Q42 110 54 108 L60 98 L66 108 Q78 110 74 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M49 99 h22 M51 104 h18" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      <path d="M47 78 Q60 86 73 78 Q60 92 47 78 Z" fill="${c.shade}" opacity=".8"/>
      ${[[53, 58], [60, 60], [67, 58], [55, 66], [65, 66]].map(([x, y]) => `<path d="M${x} ${y} v4" stroke="${c.shade}" stroke-width="1.5" stroke-linecap="round" opacity=".6"/>`).join("")}
      ${wings(c)}
      <path d="M60 18 C46 18 41 30 44 43 Q52 48 60 48 Q68 48 76 43 C79 30 74 18 60 18 Z" fill="${c.shade}"/>
      ${brow(c)}
      ${reye(50, 35)}${reye(70, 35)}
      ${hookbeak(60, 45, 1.05)}
    </g>
    ${talons([50, 70], 99)}`; },

  // Vulture — hunched heavy body, small BALD wrinkled head on a bare neck, pale feather ruff, big hook
  vulture: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag"><path d="M44 96 Q40 110 54 108 L60 100 L66 108 Q80 110 76 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${body(HUNCHC, c)}
      <path d="M60 52 C50 52 44 64 46 80 C48 96 54 100 60 100 C66 100 72 96 74 80 C76 64 70 52 60 52 Z" fill="${B}"/>
      ${wings(c)}
      ${pom(60, 48, 15, B, c.line, 11, 2)}
      <ellipse cx="60" cy="33" rx="12" ry="13" fill="${ACC2}" stroke="${c.line}" stroke-width="2"/>
      <path d="M52 28 q4 3 3 7 M68 28 q-4 3 -3 7 M55 24 q5 2 10 0" stroke="${deepen(ACC2, .25)}" stroke-width="1.2" fill="none" opacity=".7"/>
      ${reye(54, 32, 3.2)}${reye(66, 32, 3.2)}
      ${hookbeak(60, 38, 1.15)}
    </g>
    ${talons([51, 69], 99)}`; },

  // Condor — colossal: bald head with a fleshy crown-comb, big white neck ruff, massive body
  condor: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag"><path d="M43 96 Q38 112 54 110 L60 100 L66 110 Q82 112 77 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${body(BIGC, c)}
      <path d="M60 54 C48 54 41 68 43 84 C45 100 53 104 60 104 C67 104 75 100 77 84 C79 68 72 54 60 54 Z" fill="${B}"/>
      ${wings(c)}
      ${pom(60, 50, 19, WHT, c.line, 13, 2.2)}
      <path d="M52 20 Q60 11 68 20 Q60 25 52 20 Z" fill="${ACC2}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="33" rx="14" ry="15" fill="${ACC2}" stroke="${c.line}" stroke-width="2"/>
      <path d="M52 30 q4 3 3 7 M68 30 q-4 3 -3 7" stroke="${deepen(ACC2, .25)}" stroke-width="1.2" fill="none" opacity=".7"/>
      ${reye(53, 31, 3.4)}${reye(67, 31, 3.4)}
      ${hookbeak(60, 39, 1.35)}
    </g>
    ${talons([50, 70], 99)}`; },

  // Caracara — long-legged ground raptor: flat black cap, bare orange face, white throat
  caracara: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 25)}
    <g class="tail-wag"><path d="M50 92 Q47 106 58 104 L60 96 L62 104 Q73 106 70 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M52 97 h16" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    ${legfoot(53, 96, 111)}${legfoot(67, 96, 111)}
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      <path d="M60 46 Q50 50 48 60 Q60 66 72 60 Q70 50 60 46 Z" fill="${c.shade}" opacity=".7"/>
      ${wings(c)}
      <path d="M44 30 Q60 22 76 30 L76 35 Q60 30 44 35 Z" fill="${c.shade}"/>
      <path d="M50 35 Q60 41 70 35 L69 43 Q60 47 51 43 Z" fill="${ACC2}"/>
      ${reye(52, 33)}${reye(68, 33)}
      ${hookbeak(60, 42, 0.95)}
    </g>`; },

  // Goshawk — fierce accipiter: bold white eyebrow stripe, red-ringed glare, finely barred breast
  goshawk: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag"><path d="M48 94 Q44 112 56 110 L60 100 L64 110 Q76 112 72 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M51 99 h18 M52 105 h16" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      ${[58, 66, 74, 82].map((y) => `<path d="M48 ${y} q12 4 24 0" stroke="${c.shade}" stroke-width="1.5" fill="none" opacity=".7"/>`).join("")}
      ${wings(c)}
      <path d="M60 18 C46 18 41 30 44 43 Q52 48 60 48 Q68 48 76 43 C79 30 74 18 60 18 Z" fill="${c.shade}"/>
      <path d="M42 30 Q52 27 58 31 L57 35 Q51 32 44 34 Z" fill="${WHT}"/>${mirror(`<path d="M42 30 Q52 27 58 31 L57 35 Q51 32 44 34 Z" fill="${WHT}"/>`)}
      ${reye(50, 35)}${reye(70, 35)}
      ${hookbeak(60, 45, 1)}
    </g>
    ${talons([50, 70], 99)}`; },

  // Merlin — small, dashing, powerful: heavily streaked breast, faint moustache, compact stance
  merlin: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 25)}
    <g class="tail-wag"><path d="M52 94 Q49 110 60 108 Q71 110 68 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M54 100 h12 M55 105 h10" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      ${breast(B)}
      ${[[54, 56], [60, 56], [66, 56], [56, 64], [64, 64], [60, 72], [54, 72], [66, 72]].map(([x, y]) => `<path d="M${x} ${y} v5" stroke="${c.shade}" stroke-width="1.5" stroke-linecap="round" opacity=".6"/>`).join("")}
      ${wings(c)}
      <path d="M60 18 C47 18 43 30 45 42 Q52 46 60 46 Q68 46 75 42 C77 30 73 18 60 18 Z" fill="${c.shade}"/>
      <path d="M54 40 L52 48 L56 47 Z" fill="${c.shade}"/><path d="M66 40 L68 48 L64 47 Z" fill="${c.shade}"/>
      ${reye(51, 34)}${reye(69, 34)}
      ${hookbeak(60, 44, 0.88)}
    </g>
    ${talons([51, 69], 99)}`; },

  // Golden Eagle — powerful: golden nape hackles, heavy hooked beak, feathered shoulders, big talons
  goldeneagle: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 31)}
    <g class="tail-wag"><path d="M45 96 Q40 112 54 110 L60 100 L66 110 Q80 112 75 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M49 101 h22" stroke="${c.line}" stroke-width="1.2" opacity=".4"/></g>
    <g class="breathe">
      ${body(BIGC, c)}
      ${breast(B)}
      ${wings(c)}
      <path d="M60 16 C45 16 40 28 42 41 Q52 46 60 46 Q68 46 78 41 C80 28 75 16 60 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M44 33 Q60 24 76 33 Q73 44 60 46 Q47 44 44 33 Z" fill="${ACC}" opacity=".92" stroke="${c.line}" stroke-width="1"/>
      ${[48, 56, 64, 72].map((x) => `<path d="M${x} 30 l${x < 60 ? -2 : 2} -6" stroke="${deepen(ACC, .18)}" stroke-width="1.2" stroke-linecap="round" opacity=".7"/>`).join("")}
      ${brow(c)}
      ${reye(49, 37)}${reye(71, 37)}
      ${hookbeak(60, 47, 1.3)}
    </g>
    ${talons([49, 71], 99)}`; },

  // Sea Eagle — huge pale head and an ENORMOUS bright-yellow hooked beak, white tail fan
  seaeagle: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 31)}
    <g class="tail-wag"><path d="M44 96 Q39 112 54 110 L60 101 L66 110 Q81 112 76 96 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${body(BIGC, c)}
      ${breast(B)}
      ${wings(c)}
      <path d="M60 16 C45 16 39 28 41 42 Q52 47 60 47 Q68 47 79 42 C81 28 75 16 60 16 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M44 39 Q52 44 58 43 M76 39 Q68 44 62 43" stroke="${c.shade}" stroke-width="1.2" fill="none" opacity=".5"/>
      ${reye(49, 34)}${reye(71, 34)}
      <path d="M42 30 Q50 28 55 31 L54 35 Q49 32 43 33 Z" fill="${c.shade}" opacity=".55"/>${mirror(`<path d="M42 30 Q50 28 55 31 L54 35 Q49 32 43 33 Z" fill="${c.shade}" opacity=".55"/>`)}
      ${hookbeak(60, 42, 1.7)}
    </g>
    ${talons([49, 71], 99)}`; },

  // Red Kite — elegant flier: deeply FORKED tail, slim reddish body, small head, long folded wings
  redkite: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 25)}
    <g class="tail-wag">
      <path d="M50 92 L42 113 L54 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M70 92 L78 113 L66 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 94 L60 104 L66 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${body(SLIMC, c)}
      ${breast(B)}
      ${[60, 70, 80].map((y) => `<path d="M50 ${y} q10 3 20 0" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/>`).join("")}
      ${wings(c)}
      <path d="M60 22 C50 22 45 32 47 44 Q53 49 60 49 Q67 49 73 44 C75 32 70 22 60 22 Z" fill="${B}" stroke="${c.line}" stroke-width="1.2"/>
      ${reye(52, 36)}${reye(68, 36)}
      ${hookbeak(60, 45, 0.9)}
    </g>
    ${talons([52, 68], 100)}`; },

  // Secretary Bird — tall crane-legged raptor: back-swept quill crest, long body, long central tail plumes
  secretarybird: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 20)}
    <g class="tail-wag"><path d="M56 78 Q54 100 52 112 M64 78 Q66 100 68 112" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M56 78 Q54 100 52 112 M64 78 Q66 100 68 112" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/></g>
    ${legfoot(54, 80, 112)}${legfoot(66, 80, 112)}
    <path d="M50 78 Q60 72 70 78 L70 92 Q60 96 50 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe">
      <path d="M60 30 C54 30 52 36 53 42 C44 46 40 58 42 72 C44 82 52 84 60 84 C68 84 76 82 78 72 C80 58 76 46 67 42 C68 36 66 30 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 46 C52 46 48 56 49 66 C50 76 55 80 60 80 C65 80 70 76 71 66 C72 56 68 46 60 46 Z" fill="${B}"/>
      ${[[46, 12], [51, 8], [57, 7], [63, 8], [68, 12]].map(([tx, ty]) => `<path d="M60 34 Q${((60 + tx) / 2).toFixed(0)} 24 ${tx} ${ty}" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round"/><ellipse cx="${tx}" cy="${ty}" rx="1.8" ry="3.6" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" transform="rotate(${((tx - 60) * 2).toFixed(0)} ${tx} ${ty})"/>`).join("")}
      <path d="M50 38 Q60 34 70 38 Q69 48 60 50 Q51 48 50 38 Z" fill="${ACC2}" opacity=".9"/>
      ${reye(54, 41, 3.4)}${reye(66, 41, 3.4)}
      ${hookbeak(60, 50, 0.85)}
    </g>`; },

  // Barn Owl — ghostly: pale HEART-shaped facial disc, small dark eyes, tiny hooked beak
  barnowl: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 28)}
    <g class="breathe">
      ${body(OWLC, c)}
      ${[[50, 78], [60, 82], [70, 78], [46, 68], [74, 68], [56, 88], [64, 88]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.3" fill="${c.shade}" opacity=".55"/>`).join("")}
      <path d="M60 40 C56 32 44 30 39 40 C34 50 40 64 60 88 C80 64 86 50 81 40 C76 30 64 32 60 40 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${ceye(50, 52, 4.4)}${ceye(70, 52, 4.4)}
      <path d="M60 58 Q63 62 60 68 Q57 62 60 58 Z" fill="${ACC}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
    </g>
    ${talons([53, 67], 101)}`; },

  // Great Horned Owl — big ear tufts, round facial disc, huge fierce yellow eyes, small hook
  greathornedowl: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 30)}
    <g class="breathe">
      ${body(OWLC, c)}
      ${tufts(c, 42, 33, 12)}
      ${disc(c, B)}
      ${[[52, 84], [60, 87], [68, 84]].map(([x, y]) => `<path d="M${x} ${y} q3 3 6 0" stroke="${c.shade}" stroke-width="1.3" fill="none" opacity=".5"/>`).join("")}
      ${reye(48, 56, 7)}${reye(72, 56, 7)}
      <path d="M40 46 q8 -4 16 0 M64 46 q8 -4 16 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/>
      ${hookbeak(60, 64, 0.72)}
    </g>
    ${talons([53, 67], 101)}`; },

  // Screech Owl — small, camouflaged: modest ear tufts, big eyes, streaky face, compact
  screechowl: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 27)}
    <g class="breathe">
      ${body(OWLC, c)}
      ${tufts(c, 45, 34, 22)}
      ${disc(c, B)}
      ${[[50, 44], [60, 42], [70, 44]].map(([x, y]) => `<path d="M${x} ${y} v6" stroke="${c.shade}" stroke-width="1.3" stroke-linecap="round" opacity=".5"/>`).join("")}
      ${reye(49, 57, 6.2)}${reye(71, 57, 6.2)}
      <path d="M42 49 q7 -3 14 0 M64 49 q7 -3 14 0" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/>
      ${hookbeak(60, 65, 0.66)}
    </g>
    ${talons([53, 67], 101)}`; },

  // Burrowing Owl — round-headed, NO tufts, comically long legs, big eyes, white eyebrows
  burrowingowl: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 22)}
    ${legfoot(53, 84, 112)}${legfoot(67, 84, 112)}
    <g class="breathe">
      <path d="M60 20 C40 20 30 38 30 58 C30 78 44 88 60 88 C76 88 90 78 90 58 C90 38 80 20 60 20 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 44 C48 44 42 54 43 66 C44 78 52 84 60 84 C68 84 76 78 77 66 C78 54 72 44 60 44 Z" fill="${B}"/>
      ${[[50, 72], [60, 74], [70, 72], [55, 80], [65, 80]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.4" fill="${c.shade}" opacity=".55"/>`).join("")}
      <path d="M42 40 Q52 36 58 40 L57 44 Q51 41 44 43 Z" fill="${WHT}"/>${mirror(`<path d="M42 40 Q52 36 58 40 L57 44 Q51 41 44 43 Z" fill="${WHT}"/>`)}
      ${reye(50, 46, 6.4)}${reye(70, 46, 6.4)}
      ${hookbeak(60, 54, 0.66)}
    </g>`; },

  // Eagle Owl — massive: tall ear tufts, huge blazing orange eyes, deep facial disc, streaked chest
  eagleowl: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 32)}
    <g class="breathe">
      <path d="M60 12 C36 12 25 33 25 58 C25 88 40 108 60 108 C80 108 95 88 95 58 C95 33 84 12 60 12 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${tufts(c, 40, 32, 8)}
      <path d="M60 30 C40 30 30 45 30 60 C30 80 43 94 60 94 C77 94 90 80 90 60 C90 45 80 30 60 30 Z" fill="${B}" stroke="${c.line}" stroke-width="1.4"/><path d="M60 33 V90" stroke="${c.shade}" stroke-width="1" opacity=".35"/>
      ${[[50, 86], [60, 90], [70, 86], [54, 80], [66, 80]].map(([x, y]) => `<path d="M${x} ${y} v5" stroke="${c.shade}" stroke-width="1.5" stroke-linecap="round" opacity=".55"/>`).join("")}
      <circle cx="47" cy="56" r="8.4" fill="${ACC2}" stroke="${INK}" stroke-width="1.2"/><circle cx="47" cy="56" r="4.4" fill="${INK}"/><circle cx="44.6" cy="53.6" r="2" fill="#fff"/>
      <circle cx="73" cy="56" r="8.4" fill="${ACC2}" stroke="${INK}" stroke-width="1.2"/><circle cx="73" cy="56" r="4.4" fill="${INK}"/><circle cx="70.6" cy="53.6" r="2" fill="#fff"/>
      <path d="M38 45 q9 -4 18 0 M64 45 q9 -4 18 0" stroke="${c.shade}" stroke-width="1.7" fill="none" opacity=".6"/>
      ${hookbeak(60, 65, 0.82)}
    </g>
    ${talons([52, 68], 102)}`; },

  // Harpy Eagle — apex hunter: big split double crest, powerful pale disc, ENORMOUS talons
  harpyeagle: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 32)}
    <g class="tail-wag"><path d="M45 94 Q40 110 54 108 L60 99 L66 108 Q80 110 75 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${body(BIGC, c)}
      <path d="M60 52 C47 52 40 66 42 84 C44 100 53 104 60 104 C67 104 76 100 78 84 C80 66 73 52 60 52 Z" fill="${B}"/>
      <path d="M42 62 Q60 70 78 62" stroke="${c.shade}" stroke-width="2.4" fill="none" opacity=".7"/>
      ${wings(c)}
      <path d="M50 30 L40 8 L57 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M70 30 L80 8 L63 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 15 C45 15 39 27 41 41 Q52 47 60 47 Q68 47 79 41 C81 27 75 15 60 15 Z" fill="${B}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M46 40 Q60 34 74 40" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/>
      ${reye(50, 34, 4.4)}${reye(70, 34, 4.4)}
      ${hookbeak(60, 43, 1.25)}
    </g>
    ${[50, 70].map((x) => `<path d="M${x} 98 l0 8 M${x - 7} 106 h14 M${x - 6} 106 l-3 6 M${x + 6} 106 l3 6 M${x} 106 l0 6" stroke="${ACC}" stroke-width="3.2" fill="none" stroke-linecap="round"/>`).join("")}`; },

  // Bateleur — short-tailed acrobat eagle: bare red-orange face, stubby tail, bold two-tone plumage
  bateleur: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 28)}
    <g class="tail-wag"><path d="M52 98 Q52 108 60 108 Q68 108 68 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${body(BODC, c)}
      <path d="M40 52 Q30 72 38 94 Q46 74 47 56 Z" fill="${c.shade}"/>${mirror(`<path d="M40 52 Q30 72 38 94 Q46 74 47 56 Z" fill="${c.shade}"/>`)}
      <path d="M60 48 C51 48 46 58 47 72 C48 86 54 92 60 92 C66 92 72 86 73 72 C74 58 69 48 60 48 Z" fill="${B}"/>
      <path d="M60 18 C46 18 41 30 43 43 Q52 48 60 48 Q68 48 77 43 C79 30 74 18 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M47 33 Q60 27 73 33 Q71 45 60 48 Q49 45 47 33 Z" fill="${ACC2}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${reye(52, 34)}${reye(68, 34)}
      ${hookbeak(60, 43, 1.05)}
    </g>
    ${talons([51, 69], 96)}`; },
};

export const ROSTER_RAPTORS = [
  { n: "Osprey", e: "🦅", tier: 2, float: false },
  { n: "Kestrel", e: "🦅", tier: 2, float: false },
  { n: "Harrier", e: "🦅", tier: 2, float: false },
  { n: "Buzzard", e: "🦅", tier: 2, float: false },
  { n: "Vulture", e: "🦅", tier: 2, float: false },
  { n: "Condor", e: "🦅", tier: 3, float: false },
  { n: "Caracara", e: "🦅", tier: 2, float: false },
  { n: "Goshawk", e: "🦅", tier: 2, float: false },
  { n: "Merlin", e: "🦅", tier: 2, float: false },
  { n: "Golden Eagle", e: "🦅", tier: 3, float: false },
  { n: "Sea Eagle", e: "🦅", tier: 3, float: false },
  { n: "Red Kite", e: "🦅", tier: 2, float: false },
  { n: "Secretary Bird", e: "🦅", tier: 3, float: false },
  { n: "Barn Owl", e: "🦉", tier: 2, float: false },
  { n: "Great Horned Owl", e: "🦉", tier: 2, float: false },
  { n: "Screech Owl", e: "🦉", tier: 1, float: false },
  { n: "Burrowing Owl", e: "🦉", tier: 1, float: false },
  { n: "Eagle Owl", e: "🦉", tier: 3, float: false },
  { n: "Harpy Eagle", e: "🦅", tier: 4, float: false },
  { n: "Bateleur", e: "🦅", tier: 2, float: false },
];
