// songbirds.js — BESPOKE hand-drawn SVG art for SONGBIRDS (small perched birds, NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// House style: ONE continuous body silhouette (c.body + c.line), a pale two-tone belly (belly(c)) and a
// darker folded wing (c.shade), a clean cute face (big glossy eye), twig legs + a ground shadow so it sits.
// All perched, facing right (head right, tail left, beak +x). Appendages (tail/wing/crest) root INSIDE the
// body so nothing floats. Coat from `c`: c.body fill / c.shade accent / c.line outline; dark species marks
// derive from the coat via deepen(c.body,f) so they recolour at hatch. Beaks/legs use fixed warm accents.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk } from "../pets-draw.js";

const BEAK = "#f2a03b";   // conical / pointed bill
const BEAKD = "#d97b2c";  // lower-mandible / bill shading
const LEG = "#e79a3a";    // scaly perching legs
const WHT = "#fbf6ee";    // cheek / wing-bar / eye-ring highlight (not coat — a highlight)
const YEL = "#f4c84a";    // waxwing tail-tip / meadowlark accent
const WAX = "#e0564d";    // waxwing red wing-tips

// twig songbird legs: thin scaly legs with three splayed toes gripping a perch
const legs = (xs, y = 90, h = 12) => xs.map((x) =>
  `<path d="M${x} ${y} l0 ${h} M${x} ${y + h} l-4 4 M${x} ${y + h} l4 4 M${x} ${y + h} l0 5" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");

export const ART_SONGBIRDS = {
  // Finch — small round seed-eater: stout conical bill, faintly notched tail, streaky folded wing
  finch: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag"><path d="M40 80 L33 98 L40 94 L46 98 L48 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="76" rx="18" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 76 Q57 66 66 76 Q68 88 57 90 Q48 88 48 76 Z" fill="${B}"/>
      <path d="M52 78 l0 7 M57 79 l0 8 M62 79 l0 7" stroke="${deepen(c.body, 0.42)}" stroke-width="1.7" stroke-linecap="round" opacity=".7"/>
      <path d="M62 62 Q77 66 76 82 Q68 76 60 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M64 68 h9 M63 73 h9" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    ${legs([52, 64], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 49 L91 53 L76 57 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M76 53 L91 53 L76 57 Z" fill="${BEAKD}"/>
      ${eye(66, 50, 3, eyeInk(c))}
    </g>`; },

  // Warbler — slim active insect-eater: fine sharp bill, pale eye-ring, plain neat wing
  warbler: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 20)}
    <g class="tail-wag"><path d="M42 80 Q33 96 40 97 L48 83 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="76" rx="16" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M49 76 Q57 67 65 76 Q67 87 57 89 Q49 87 49 76 Z" fill="${B}"/>
      <path d="M62 63 Q75 67 74 82 Q67 76 60 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 63], 89, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="11.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M75 50 L92 51 L75 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="66" cy="50" r="4.4" fill="none" stroke="${WHT}" stroke-width="1.6"/>
      ${eye(66, 50, 2.8, eyeInk(c))}
    </g>`; },

  // Wren — tiny rounded bird with the classic cocked-UP barred tail, fine slightly-decurved bill
  wren: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 20)}
    <g class="tail-wag">
      <path d="M44 68 Q34 48 26 56 Q34 60 41 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M31 56 l6 4 M28 61 l7 3 M27 66 l7 2" stroke="${c.line}" stroke-width="1.1" opacity=".5"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="78" rx="16" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 78 Q58 69 66 78 Q68 88 58 90 Q50 88 50 78 Z" fill="${B}"/>
      <path d="M63 66 Q76 70 75 84 Q68 78 61 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M64 71 h9 M64 76 h8" stroke="${c.line}" stroke-width="1" opacity=".4"/></g>
    ${legs([53, 64], 91, 11)}
    <g class="head-tilt">
      <circle cx="66" cy="54" r="11.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M61 49 q6 -2 11 1" stroke="${WHT}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M77 52 Q86 51 90 55 Q84 55 78 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(67, 52, 2.9, eyeInk(c))}
    </g>`; },

  // Chickadee — round with a bold dark CAP + throat BIB and a bright white cheek, tiny stubby bill
  chickadee: (c) => { const B = belly(c), D = deepen(c.body, 0.58); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M40 80 Q30 98 38 99 L47 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 76 Q57 67 66 76 Q68 88 57 90 Q48 88 48 76 Z" fill="${B}"/>
      <path d="M62 63 Q76 67 75 82 Q68 76 60 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="12.5" fill="${WHT}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M53 50 Q54 40 65 40 Q77 41 77 52 Q65 45 53 50 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M72 56 Q69 66 61 63 Q64 58 68 55 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M76 52 L88 54 L76 57 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(63, 51, 3, INK)}
    </g>`; },

  // Nuthatch — big-headed, short-tailed clinger: long straight dagger bill, dark eye-line stripe
  nuthatch: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M44 82 Q37 92 44 92 L51 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="78" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M47 78 Q56 69 65 78 Q67 88 56 90 Q47 88 47 78 Z" fill="${B}"/>
      <path d="M61 66 Q75 70 74 84 Q67 78 59 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([51, 62], 90, 12)}
    <g class="head-tilt">
      <circle cx="66" cy="50" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 45 L79 45" stroke="${D}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M77 49 L97 49 L77 53 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M77 51 L97 49 L77 53 Z" fill="${BEAKD}"/>
      ${eye(67, 49, 3, eyeInk(c))}
    </g>`; },

  // Titmouse — trim grey bird with a jaunty pointed CREST, big dark eye, small neat bill
  titmouse: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M40 80 Q30 100 38 102 L47 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 77 Q57 68 66 77 Q68 88 57 90 Q48 88 48 77 Z" fill="${B}"/>
      <path d="M62 64 Q76 68 75 83 Q68 77 60 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <path d="M60 45 L63 22 L71 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="65" cy="52" r="12.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M77 51 L89 53 L77 56 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(66, 51, 3.3, eyeInk(c))}
    </g>`; },

  // Oriole — sleek with a dark HOOD over the head, sharp pointed bill, bright body, white wing-bar
  oriole: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M40 80 Q30 99 38 100 L48 84 Z" fill="${D}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 78 Q57 70 65 78 Q67 88 57 90 Q48 88 48 78 Z" fill="${B}"/>
      <path d="M61 63 Q76 67 75 83 Q68 77 59 77 Z" fill="${D}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 70 h11" stroke="${WHT}" stroke-width="1.8" opacity=".9"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="51" r="12.5" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 49 L93 50 L76 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${eye(66, 49, 3, "#e9edf2")}
    </g>`; },

  // Tanager — stout tropical bird: chunky body, thick short bill, contrasting dark wing, big eye
  tanager: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 23)}
    <g class="tail-wag"><path d="M40 80 Q29 100 37 101 L48 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="77" rx="19" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 77 Q56 67 66 77 Q68 89 56 91 Q46 89 46 77 Z" fill="${B}"/>
      <path d="M60 62 Q77 66 76 84 Q68 77 58 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${legs([51, 63], 91, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="50" r="13.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 45 L96 51 L76 58 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M76 51 L96 51 L76 58 Z" fill="${BEAKD}"/>
      ${eye(66, 48, 3.2, eyeInk(c))}
    </g>`; },

  // Indigo Bunting — small, uniformly coloured, roundish: neat silvery conical bill, plain smooth wing
  indigobunting: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M41 80 Q31 97 39 98 L48 83 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M49 78 Q57 71 65 78 Q66 86 57 88 Q49 86 49 78 Z" fill="${B}" opacity=".7"/>
      <path d="M62 65 Q76 69 74 83 Q68 77 60 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M75 47 L87 53 L75 59 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M75 53 L87 53 L75 59 Z" fill="${tint(c.shade, 0.4)}"/>
      ${eye(66, 50, 3, eyeInk(c))}
    </g>`; },

  // Grosbeak — dominated by a MASSIVE pale conical bill, oversized head, thick-necked chunky body
  grosbeak: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 23)}
    <g class="tail-wag"><path d="M40 80 Q30 98 38 99 L48 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="55" cy="78" rx="19" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M45 78 Q55 68 65 78 Q67 90 55 92 Q45 90 45 78 Z" fill="${B}"/>
      <path d="M60 63 Q77 67 76 85 Q68 78 58 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${legs([50, 62], 92, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="49" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M73 41 L98 50 L73 62 Q69 51 73 41 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M73 51 L98 50 L73 62 Z" fill="${tint(c.shade, 0.35)}"/>
      ${eye(66, 46, 3.2, eyeInk(c))}
    </g>`; },

  // Wood Thrush — upright, warm-backed with a boldly dark-SPOTTED pale breast, fine bill
  woodthrush: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M40 80 Q30 99 38 100 L48 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M47 76 Q57 66 67 76 Q69 89 57 91 Q47 89 47 76 Z" fill="${B}"/>
      <path d="M61 63 Q76 67 75 83 Q68 77 59 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${[[52, 74], [60, 76], [55, 82], [63, 84], [50, 84]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.9" fill="${D}"/>`).join("")}</g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="66" cy="51" r="12.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M77 50 L91 53 L77 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${eye(67, 49, 3, eyeInk(c))}
    </g>`; },

  // Nightingale — plump plain warm bird caught mid-song: bill held OPEN, rounded rufous-toned tail
  nightingale: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag"><path d="M40 80 Q29 100 39 101 L49 85 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 77 Q57 68 66 77 Q68 88 57 90 Q48 88 48 77 Z" fill="${B}"/>
      <path d="M62 63 Q76 67 75 83 Q68 77 60 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="50" r="12.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 46 L92 43 L78 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M77 52 L91 57 L78 55 Z" fill="${BEAKD}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M78 50 L90 51 L78 54 Z" fill="${INK}" opacity=".55"/>
      ${eye(66, 48, 3, eyeInk(c))}
    </g>`; },

  // Skylark — streaky ground bird with a short ragged CREST and finely streaked back/wing
  skylark: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag"><path d="M40 80 Q30 100 38 101 L48 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 78 Q57 70 65 78 Q67 88 57 90 Q48 88 48 78 Z" fill="${B}"/>
      <path d="M61 63 Q76 67 75 83 Q68 77 59 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 70 l3 6 M56 68 l3 7 M63 70 l3 6 M69 73 l2 6" stroke="${D}" stroke-width="1.3" stroke-linecap="round" opacity=".7"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <path d="M57 44 l-1 -8 l4 6 l2 -8 l3 8 l4 -6 l1 8 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="65" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 50 L89 53 L76 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${eye(66, 51, 3, eyeInk(c))}
    </g>`; },

  // Barn Swallow — sleek aerial bird: deeply FORKED streamer tail, swept pointed wing, small bill, rufous throat
  barnswallow: (c) => { const B = belly(c), D = deepen(c.body, 0.4); return `
    ${floorShadow(52, 110, 22)}
    <g class="tail-wag">
      <path d="M43 78 L22 106 L31 103 L46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 80 L40 108 L48 101 L52 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="17" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M49 74 Q58 66 67 74 Q69 84 58 86 Q49 84 49 74 Z" fill="${B}"/>
      <path d="M62 60 Q84 62 80 82 Q70 74 60 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${legs([54, 64], 86, 10)}
    <g class="head-tilt">
      <circle cx="66" cy="51" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 57 Q66 62 72 57 Q66 60 60 57 Z" fill="${D}"/>
      <path d="M77 51 L88 53 L77 55 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      ${eye(67, 49, 3, eyeInk(c))}
    </g>`; },

  // Starling — chesty upright bird spangled with pale SPECKLES all over, long pointed straight bill
  starling: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag"><path d="M42 82 Q34 94 41 95 L49 85 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M42 84 Q40 58 60 54 Q80 58 78 84 Q60 94 42 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 70 Q60 62 70 70 Q72 84 60 88 Q48 84 50 70 Z" fill="${B}" opacity=".55"/>
      ${[[52, 66], [60, 64], [67, 68], [55, 74], [63, 76], [58, 82], [69, 80], [50, 80], [66, 60], [72, 74]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.5" fill="${WHT}"/>`).join("")}</g>
    ${legs([53, 65], 90, 12)}
    <g class="head-tilt">
      <circle cx="61" cy="48" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[[54, 42], [60, 40], [66, 44], [56, 52]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.4" fill="${WHT}"/>`).join("")}
      <path d="M73 45 L94 47 L73 51 Z" fill="${YEL}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${eye(64, 46, 3, eyeInk(c))}
    </g>`; },

  // Mockingbird — slim grey bird with a notably LONG tail and a flashing white wing-patch, slightly decurved bill
  mockingbird: (c) => { const B = belly(c); return `
    ${floorShadow(56, 112, 22)}
    <g class="tail-wag"><path d="M40 82 Q28 112 40 113 L50 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M42 90 L48 88 M41 98 L47 96 M40 106 L46 104" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="74" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 74 Q57 65 66 74 Q68 85 57 87 Q48 85 48 74 Z" fill="${B}"/>
      <path d="M61 61 Q77 65 76 82 Q68 75 59 75 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 68 Q73 70 74 78 Q68 76 65 74 Z" fill="${WHT}"/></g>
    ${legs([52, 63], 88, 11)}
    <g class="head-tilt">
      <circle cx="66" cy="50" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M77 49 Q88 49 91 53 Q84 53 77 53 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(67, 48, 3, eyeInk(c))}
    </g>`; },

  // Cedar Waxwing — silky bird with a smooth swept-back CREST, black MASK, yellow tail-tip, red wax wing-tips
  cedarwaxwing: (c) => { const B = belly(c), D = deepen(c.body, 0.62); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M41 80 Q31 99 39 100 L48 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M33 96 L46 92 L44 100 Z" fill="${YEL}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 78 Q57 70 66 78 Q68 88 57 90 Q48 88 48 78 Z" fill="${B}"/>
      <path d="M61 63 Q76 67 75 83 Q68 77 59 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M72 72 l3 2 M71 77 l3 2" stroke="${WAX}" stroke-width="2.2" stroke-linecap="round"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <path d="M62 43 Q50 30 43 34 Q52 40 57 49 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="65" cy="51" r="12.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 48 Q66 45 78 49 L77 54 Q66 51 57 53 Z" fill="${D}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>
      <path d="M77 50 L89 52 L77 55 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      ${eye(66, 50, 2.9, "#e9edf2")}
    </g>`; },

  // Goldfinch — round bright finch with a dark forehead CAP, dark wing bearing a white bar, conical bill
  goldfinch: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 110, 21)}
    <g class="tail-wag"><path d="M41 80 L34 97 L40 93 L45 97 L48 83 Z" fill="${D}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M49 77 Q57 68 65 77 Q67 88 57 90 Q49 88 49 77 Z" fill="${B}"/>
      <path d="M61 63 Q77 67 76 84 Q68 77 59 77 Z" fill="${D}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 71 h12" stroke="${WHT}" stroke-width="2" opacity=".95"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 44 Q66 40 74 45 Q66 44 61 48 Z" fill="${D}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M76 50 L89 53 L76 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(66, 51, 3, eyeInk(c))}
    </g>`; },

  // Meadowlark — chunky, big-headed with a bright pale breast crossed by a bold dark V, long pointed bill
  meadowlark: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 110, 23)}
    <g class="tail-wag"><path d="M40 80 Q30 98 38 99 L48 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="78" rx="19" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 76 Q56 66 66 76 Q68 90 56 92 Q46 90 46 76 Z" fill="${B}"/>
      <path d="M50 74 L57 84 L64 74" fill="none" stroke="${D}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M61 63 Q76 67 75 84 Q68 78 59 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${legs([51, 63], 92, 12)}
    <g class="head-tilt">
      <circle cx="66" cy="49" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M77 47 L96 50 L77 53 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M77 50 L96 50 L77 53 Z" fill="${BEAKD}"/>
      ${eye(67, 47, 3.1, eyeInk(c))}
    </g>`; },

  // Chaffinch — tidy round finch with DOUBLE white wing-bars, conical bill, pale-flushed breast
  chaffinch: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag"><path d="M40 80 Q30 99 38 100 L48 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="57" cy="77" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 76 Q57 66 66 76 Q68 89 57 91 Q48 89 48 76 Z" fill="${B}"/>
      <path d="M61 63 Q76 67 75 83 Q68 77 59 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 69 h12 M63 75 h11" stroke="${WHT}" stroke-width="1.9"/></g>
    ${legs([52, 63], 90, 12)}
    <g class="head-tilt">
      <circle cx="65" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 50 L90 53 L76 57 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M76 53 L90 53 L76 57 Z" fill="${BEAKD}"/>
      ${eye(66, 50, 3, eyeInk(c))}
    </g>`; },
};

export const ROSTER_SONGBIRDS = [
  { n: "Finch", e: "🐦", tier: 1, float: false },
  { n: "Warbler", e: "🐦", tier: 1, float: false },
  { n: "Wren", e: "🐦", tier: 1, float: false },
  { n: "Chickadee", e: "🐦", tier: 1, float: false },
  { n: "Nuthatch", e: "🐦", tier: 1, float: false },
  { n: "Titmouse", e: "🐦", tier: 1, float: false },
  { n: "Oriole", e: "🐦", tier: 2, float: false },
  { n: "Tanager", e: "🐦", tier: 2, float: false },
  { n: "Indigo Bunting", e: "🐦", tier: 1, float: false },
  { n: "Grosbeak", e: "🐦", tier: 2, float: false },
  { n: "Wood Thrush", e: "🐦", tier: 1, float: false },
  { n: "Nightingale", e: "🐦", tier: 2, float: false },
  { n: "Skylark", e: "🐦", tier: 1, float: false },
  { n: "Barn Swallow", e: "🐦", tier: 1, float: false },
  { n: "Starling", e: "🐦", tier: 1, float: false },
  { n: "Mockingbird", e: "🐦", tier: 1, float: false },
  { n: "Cedar Waxwing", e: "🐦", tier: 2, float: false },
  { n: "Goldfinch", e: "🐦", tier: 1, float: false },
  { n: "Meadowlark", e: "🐦", tier: 2, float: false },
  { n: "Chaffinch", e: "🐦", tier: 1, float: false },
];
