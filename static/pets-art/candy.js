// candy.js — BESPOKE hand-drawn SVG art for the CANDY batch (NADO Pets).
// Whimsical candy/food creatures — each is an animal/creature MADE OF the treat. Very cute.
// Contract: inner markup of <svg viewBox="0 0 120 120">, creature centered ~(60,64), within x,y ∈ [8,114].
// HOUSE STYLE: ONE continuous silhouette (c.body + c.line outline, stroke-width 3.2, round joins);
// appendages tuck/overlap (nothing floats); two-tone via belly(c)+c.shade; big glossy ceye face;
// floorShadow grounds every pet (all SIT — float:false). Body colour ALWAYS from the coat `c`
// (the game recolours each pet at hatch); only icing/sprinkles/cherry use a few bright fixed accents.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// fixed sweet accents (NOT coat — icing/sprinkles/cherry), constant across recolours
const ICING = "#fff7f2";   // pale cream icing / marshmallow gloss / candy stick
const CHERRY = "#e0564d";  // glacé cherry / red flourish
const GLOSS = "#ffffff";   // specular highlight
const SPR = ["#ff7aa8", "#ffd23f", "#5ec8e5", "#8ce99a", "#b98cff"]; // sprinkles
// one sprinkle: a tiny rounded bar at (x,y) rotated a°
const spr = (x, y, a, col) => `<rect x="${(x - 3).toFixed(1)}" y="${(y - 1).toFixed(1)}" width="6" height="2.1" rx="1" fill="${col}" transform="rotate(${a} ${x} ${y})"/>`;
// scatter n sprinkles from a fixed list of [x,y,angle]
const scatter = (pts) => pts.map(([x, y, a], i) => spr(x, y, a, SPR[i % SPR.length])).join("");

export const ART_CANDY = {
  // ── Gummy Bear — translucent jelly bear, round ears, stubby arms out, glossy sheen (t1)
  gummybear: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 25)}
    <g class="breathe">
      <path d="M60 24 C49 24 44 31 46 41 C39 39 32 44 32 52 C32 60 39 62 46 60 C44 68 45 82 48 90 L45 101 C44 107 52 108 55 103 L58 94 C59 95 61 95 62 94 L65 103 C68 108 76 107 75 101 L72 90 C75 82 76 68 74 60 C81 62 88 60 88 52 C88 44 81 39 74 41 C76 31 71 24 60 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".9"/>
      <ellipse cx="60" cy="76" rx="13" ry="16" fill="${B}" opacity=".5"/>
      <circle cx="43" cy="33" r="9" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <circle cx="77" cy="33" r="9" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M40 30 Q34 42 40 54" fill="none" stroke="${GLOSS}" stroke-width="3.4" stroke-linecap="round" opacity=".45"/>
      <circle cx="71" cy="47" r="2.6" fill="${GLOSS}" opacity=".4"/>
      <circle cx="49" cy="82" r="2.4" fill="${GLOSS}" opacity=".3"/>
      ${ceye(52, 50, 4)}${ceye(68, 50, 4)}
      <path d="M60 55 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      ${smile(60, 58, 3.2, INK)}
    </g>`;
  },

  // ── Candy Cane Serpent — barber-pole serpent curled into a cane hook, white stripes, cute snake head (t2)
  candycaneserpent: (c) => {
    const B = belly(c);
    const cane = "M46 100 Q38 66 44 48 Q49 28 68 28 Q86 28 86 48 Q86 56 80 58";
    const stripe = (x, y, a) => `<rect x="${x - 6.5}" y="${y - 2}" width="13" height="4" rx="2" fill="${ICING}" transform="rotate(${a} ${x} ${y})"/>`;
    return `
    ${floorShadow(60, 110, 24)}
    <g class="breathe">
      <ellipse cx="47" cy="99" rx="11" ry="4" fill="${c.shade}" opacity=".5"/>
      <path d="${cane}" fill="none" stroke="${c.line}" stroke-width="20" stroke-linecap="round"/>
      <path d="${cane}" fill="none" stroke="${c.body}" stroke-width="15.5" stroke-linecap="round"/>
      ${[[44, 90, -11], [42, 74, -4], [42, 57, 8], [47, 41, 26], [59, 30, 70], [75, 29, 108], [85, 39, 163]].map(([x, y, a]) => stripe(x, y, a)).join("")}
      <path d="M80 48 Q92 48 93 60 Q93 71 82 71 Q73 70 73 59 Q73 50 80 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="84" cy="64" rx="7" ry="4.5" fill="${B}"/>
      <path d="M89 68 q5 1 9 -2 M89 69 q4 4 5 8" fill="none" stroke="${CHERRY}" stroke-width="1.5" stroke-linecap="round"/>
      ${ceye(82, 58, 3.4)}
      ${smile(85, 62, 2.6, INK)}
    </g>`;
  },

  // ── Cupcake Cat — a cat whose body is a frosting-swirl cupcake, ridged wrapper, cherry, cat ears (t2)
  cupcakecat: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 28)}
    <g class="breathe">
      <path d="M35 78 L85 78 L79 104 Q60 110 41 104 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M45 80 L42 104 M55 80 L54 107 M65 80 L66 107 M75 80 L78 104" stroke="${c.line}" stroke-width="1.4" opacity=".45"/>
      <path d="M46 48 L40 30 L58 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M74 48 L80 30 L62 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M33 78 Q29 56 46 54 Q45 42 60 42 Q75 42 74 54 Q91 56 87 78 Q60 86 33 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 66 Q52 60 60 63 Q70 60 80 66" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".55"/>
      <ellipse cx="60" cy="70" rx="17" ry="9" fill="${B}" opacity=".55"/>
      <circle cx="60" cy="40" r="4.6" fill="${CHERRY}" stroke="${c.line}" stroke-width="1.6"/>
      ${ceye(51, 66, 4)}${ceye(69, 66, 4)}
      <path d="M60 71 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      ${smile(60, 74, 3, INK)}
      <path d="M46 70 h-11 M47 74 h-12 M74 70 h11 M73 74 h12" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>
    </g>`;
  },

  // ── Donut Slime — a slime shaped as a sprinkled ring donut, glossy icing, cute slime face (t2)
  donutslime: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 108, 30)}
    <g class="breathe">
      <path fill-rule="evenodd" d="M60 38 C87 38 98 56 98 74 C98 94 80 102 60 102 C40 102 22 94 22 74 C22 56 33 38 60 38 Z M60 62 C49 62 43 68 43 75 C43 82 49 86 60 86 C71 86 77 82 77 75 C77 68 71 62 60 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M24 68 Q26 44 60 42 Q94 44 96 68 Q90 66 88 72 Q84 66 80 72 Q76 65 72 71 Q64 63 60 63 Q54 62 48 71 Q44 65 40 72 Q36 66 32 72 Q28 66 24 68 Z" fill="${B}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${scatter([[40, 54, 20], [54, 50, 70], [68, 52, 120], [80, 58, 40], [33, 62, 100], [88, 64, 10], [47, 58, 150], [61, 56, 90]])}
      ${ceye(49, 90, 3.4)}${ceye(71, 90, 3.4)}
      ${smile(60, 90, 3.4, INK)}
      <circle cx="30" cy="80" r="2.4" fill="${GLOSS}" opacity=".4"/>
    </g>`;
  },

  // ── Cookie Golem — round chocolate-chip cookie creature, stubby arms & legs, warm smile (t2)
  cookiegolem: (c) => {
    const B = belly(c);
    const chip = deepen(c.body, 0.45);
    return `
    ${floorShadow(60, 110, 28)}
    <g class="tail-wag">
      ${tube("M38 74 Q24 78 22 92", c.body, c.line, 6)}<circle cx="22" cy="93" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${tube("M82 74 Q96 78 98 92", c.body, c.line, 6)}<circle cx="98" cy="93" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
    </g>
    <g class="breathe">
      ${tube("M50 92 L48 108", c.body, c.line, 7)}${tube("M70 92 L72 108", c.body, c.line, 7)}
      <path d="M60 38 Q88 38 91 66 Q93 92 60 94 Q27 92 29 66 Q32 38 60 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="74" rx="20" ry="12" fill="${B}" opacity=".4"/>
      ${[[42, 54], [76, 50], [80, 74], [40, 78], [63, 46], [70, 84]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="3.4" ry="3" fill="${chip}"/>`).join("")}
      <circle cx="48" cy="66" r="1.5" fill="${chip}"/><circle cx="72" cy="66" r="1.5" fill="${chip}"/>
      ${ceye(51, 64, 4)}${ceye(69, 64, 4)}
      <path d="M60 69 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      ${smile(60, 72, 3.2, INK)}
    </g>`;
  },

  // ── Marshmallow Puff — soft squishy pillow blob, gentle two-tone, dreamy face (t1)
  marshmallowpuff: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 108, 26)}
    <g class="breathe">
      <path d="M34 50 Q30 40 42 40 Q52 36 60 40 Q68 36 78 40 Q90 40 86 50 Q92 64 86 80 Q90 92 78 90 Q60 96 42 90 Q30 92 34 80 Q28 64 34 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 48 Q60 42 80 48" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      <ellipse cx="60" cy="76" rx="20" ry="11" fill="${B}" opacity=".55"/>
      <ellipse cx="45" cy="72" rx="4" ry="3" fill="${CHERRY}" opacity=".25"/><ellipse cx="75" cy="72" rx="4" ry="3" fill="${CHERRY}" opacity=".25"/>
      ${ceye(51, 62, 4.2)}${ceye(69, 62, 4.2)}
      <path d="M60 67 l-2 2.2 h4 Z" fill="${INK}"/>
      ${smile(60, 69, 3.2, INK)}
    </g>`;
  },

  // ── Lollipop Sprite — swirl disc head on a candy stick, tiny arms, cheerful face (t1)
  lollipopsprite: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 111, 16)}
    <g class="breathe">
      <path d="M60 74 L60 106" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
      <path d="M60 74 L60 106" stroke="${ICING}" stroke-width="5" stroke-linecap="round"/>
      ${tube("M40 62 Q30 70 30 80", c.body, c.line, 5)}${tube("M80 62 Q90 70 90 80", c.body, c.line, 5)}
      <circle cx="30" cy="81" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="90" cy="81" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="60" cy="50" r="30" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M60 50 Q68 50 68 42 Q68 32 56 32 Q40 32 40 50 Q40 70 60 70 Q84 70 84 46" fill="none" stroke="${ICING}" stroke-width="3.4" stroke-linecap="round" opacity=".75"/>
      <path d="M42 34 Q34 42 34 54" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      ${ceye(51, 50, 4)}${ceye(69, 50, 4)}
      <path d="M60 55 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      ${smile(60, 58, 3.2, INK)}
      <ellipse cx="47" cy="60" rx="4" ry="2.6" fill="${CHERRY}" opacity=".3"/><ellipse cx="73" cy="60" rx="4" ry="2.6" fill="${CHERRY}" opacity=".3"/>
    </g>`;
  },

  // ── Jelly Bean Bug — glossy bean body, six little legs, curled antennae, sweet grin (t1)
  jellybeanbug: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 108, 26)}
    <g class="breathe">
      ${[44, 60, 76].map((x) => `<path d="M${x} 82 q-2 8 -7 11" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M${x} 82 q2 8 7 11" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>`).join("")}
      <path d="M34 64 Q34 46 60 46 Q86 46 86 64 Q86 82 60 82 Q34 82 34 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 55 Q56 49 70 52" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".5"/>
      <ellipse cx="60" cy="70" rx="18" ry="8" fill="${B}" opacity=".5"/>
      <circle cx="47" cy="59" r="2.6" fill="${GLOSS}" opacity=".5"/>
      <path d="M48 48 Q44 34 36 32" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/><circle cx="35" cy="31" r="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M72 48 Q76 34 84 32" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/><circle cx="85" cy="31" r="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${ceye(52, 64, 4)}${ceye(68, 64, 4)}
      <path d="M60 69 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      ${smile(60, 72, 3, INK)}
    </g>`;
  },

  // ── Chocolate Hound — glossy chocolate dog sitting, floppy ears, big nose, shine streaks (t2)
  chocolatehound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 111, 27)}
    <g class="tail-wag"><path d="M80 96 Q100 92 96 74 Q94 66 85 68 Q92 74 87 82 Q82 90 74 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 112 C34 112 30 90 34 72 C36 62 40 56 46 52 C42 44 46 34 60 34 C74 34 78 44 74 52 C80 56 84 62 86 72 C90 90 86 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M45 46 Q28 50 29 74 Q41 74 47 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M75 46 Q92 50 91 74 Q79 74 73 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="16" ry="12" fill="${B}"/>
      <path d="M44 50 Q40 60 43 70" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      ${ceye(51, 58, 4)}${ceye(69, 58, 4)}
      <ellipse cx="60" cy="67" rx="4.4" ry="3.4" fill="${INK}"/>
      <path d="M60 70 v4 M60 74 q-4 3 -8 2 M60 74 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
    </g>`;
  },

  // ── Ice Cream Cone — waffle cone with a scoop that has the face, drips & cherry (t2)
  icecreamcone: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 20)}
    <g class="breathe">
      <path d="M44 68 L76 68 L60 108 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 74 L66 74 M54 84 L66 84 M57 94 L63 94 M52 68 L60 104 M60 68 L64 84 M68 68 L60 104" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      <path d="M34 66 Q28 44 48 42 Q52 30 66 34 Q86 34 84 54 Q94 62 82 70 Q78 64 72 70 Q66 63 60 70 Q54 63 48 70 Q42 63 34 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="58" cy="52" rx="18" ry="9" fill="${B}" opacity=".5"/>
      <path d="M42 40 Q36 48 38 58" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      <circle cx="60" cy="32" r="4.6" fill="${CHERRY}" stroke="${c.line}" stroke-width="1.6"/>
      ${ceye(51, 52, 4)}${ceye(69, 52, 4)}
      <path d="M60 57 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      ${smile(60, 60, 3, INK)}
    </g>`;
  },

  // ── Popcorn Puff — a fluffy cluster of popped kernels, buttery tone, happy face (t1)
  popcornpuff: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 27)}
    <g class="breathe">
      ${tube("M50 96 L48 108", c.body, c.line, 6)}${tube("M70 96 L72 108", c.body, c.line, 6)}
      ${pom(60, 66, 30, c.body, c.line, 14, 3.2)}
      <circle cx="40" cy="48" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <circle cx="80" cy="48" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <circle cx="60" cy="40" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="60" cy="74" rx="19" ry="10" fill="${B}" opacity=".5"/>
      ${[[42, 60], [78, 62], [50, 78], [72, 78], [60, 84]].map(([x, y]) => `<path d="M${x} ${y} q3 -4 6 0 q-3 3 -6 0 Z" fill="${c.shade}" opacity=".45"/>`).join("")}
      ${ceye(51, 64, 4)}${ceye(69, 64, 4)}
      <path d="M60 69 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      ${smile(60, 72, 3.2, INK)}
    </g>`;
  },

  // ── Pretzel Snake — a serpent knotted into a salted pretzel, salt flecks, cute head (t2)
  pretzelsnake: (c) => {
    const B = belly(c);
    const knot = "M50 40 Q22 46 22 74 Q22 96 50 96 Q74 96 76 72 M70 40 Q98 46 98 74 Q98 96 70 96 Q46 96 44 72";
    const cross = "M50 40 Q60 66 76 72 M70 40 Q60 66 44 72";
    return `
    ${floorShadow(60, 108, 30)}
    <g class="breathe">
      <path d="${knot}" fill="none" stroke="${c.line}" stroke-width="18" stroke-linecap="round"/>
      <path d="${cross}" fill="none" stroke="${c.line}" stroke-width="18" stroke-linecap="round"/>
      <path d="${knot}" fill="none" stroke="${c.body}" stroke-width="13.5" stroke-linecap="round"/>
      <path d="${cross}" fill="none" stroke="${c.body}" stroke-width="13.5" stroke-linecap="round"/>
      ${[[34, 60], [86, 60], [40, 88], [80, 88], [60, 92], [30, 78], [90, 78], [60, 62]].map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="1.6" fill="${ICING}"/>`).join("")}
      <path d="M44 40 Q40 26 50 22 Q60 24 58 38 Q52 44 44 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="51" cy="34" rx="6" ry="4" fill="${B}"/>
      <path d="M52 22 q-2 -6 3 -9 M52 22 q4 -3 9 -3" fill="none" stroke="${CHERRY}" stroke-width="1.5" stroke-linecap="round"/>
      ${ceye(49, 32, 3.2)}
      ${smile(52, 37, 2.4, INK)}
    </g>`;
  },

  // ── Waffle Turtle — turtle with a golden waffle shell, syrup drip, pat of butter, snug head (t2)
  waffleturtle: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 106, 30)}
    <g class="breathe">
      ${[[48, 78], [80, 78]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="9" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>`).join("")}
      <path d="M84 62 Q100 60 100 70 Q98 78 88 76 Q82 70 84 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M40 62 Q22 60 20 74 Q20 86 34 86 Q46 84 46 72 Q46 62 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="30" cy="76" rx="7" ry="5" fill="${B}"/>
      ${ceye(26, 72, 3.2)}
      ${smile(29, 77, 2.4, INK)}
      <path d="M32 62 Q30 40 60 38 Q90 40 88 62 Q88 74 60 76 Q32 74 32 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 50 h40 M38 60 h44 M52 40 V70 M68 40 V70" stroke="${c.line}" stroke-width="1.8" opacity=".5"/>
      <ellipse cx="60" cy="54" rx="24" ry="12" fill="${B}" opacity=".3"/>
      <rect x="53" y="44" width="9" height="8" rx="2" fill="${ICING}" stroke="${c.line}" stroke-width="1.4"/>
    </g>`;
  },

  // ── Bubblegum Blob — a bubblegum creature blowing a big glossy bubble, stretchy body (t1)
  bubblegumblob: (c) => {
    const B = belly(c);
    const bub = tint(c.body, 0.45);
    return `
    ${floorShadow(58, 108, 26)}
    <g class="breathe">
      <path d="M30 58 Q30 42 50 42 Q58 34 66 42 Q84 42 84 60 Q88 78 74 88 Q54 96 38 86 Q26 76 30 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="54" cy="74" rx="18" ry="10" fill="${B}" opacity=".55"/>
      <path d="M38 50 Q34 60 38 68" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      ${ceye(46, 58, 4)}${ceye(62, 58, 4)}
      <path d="M54 64 q-3 6 -8 6" fill="none" stroke="${INK}" stroke-width="1.5" stroke-linecap="round"/>
      <ellipse cx="74" cy="58" rx="4" ry="3" fill="${INK}" opacity=".5"/>
      <circle cx="94" cy="52" r="15" fill="${bub}" stroke="${c.line}" stroke-width="3" opacity=".82"/>
      <path d="M85 46 Q82 52 85 58" fill="none" stroke="${GLOSS}" stroke-width="2.6" stroke-linecap="round" opacity=".6"/>
      <path d="M80 56 Q84 60 90 60" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Caramel Cub — glossy caramel bear cub sitting, round ears, drippy sheen, sweet muzzle (t2)
  caramelcub: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 111, 27)}
    <g class="breathe">
      <path d="M60 112 C33 112 30 88 35 70 C38 60 43 55 49 52 C44 44 48 32 60 32 C72 32 76 44 71 52 C77 55 82 60 85 70 C90 88 87 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="42" cy="38" r="9" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <circle cx="78" cy="38" r="9" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="60" cy="66" rx="17" ry="14" fill="${B}"/>
      <ellipse cx="60" cy="70" rx="9" ry="7" fill="${tint(c.body, 0.5)}"/>
      <path d="M40 42 Q35 56 40 68" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      <path d="M74 96 Q76 104 72 108" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".6"/>
      ${ceye(51, 56, 4)}${ceye(69, 56, 4)}
      <path d="M60 66 l-2.6 2.8 h5.2 Z" fill="${INK}"/>
      ${smile(60, 69, 3.2, INK)}
    </g>`;
  },

  // ── Peppermint Owl — round owl with a peppermint pinwheel belly, ear tufts, big eyes (t2)
  peppermintowl: (c) => {
    const B = belly(c);
    const BEAK = "#f2a03b";
    return `
    ${floorShadow(60, 110, 26)}
    <g class="breathe">
      <path d="M40 46 L34 30 L50 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M80 46 L86 30 L70 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 34 Q88 36 88 66 Q88 96 60 98 Q32 96 32 66 Q32 36 60 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 60 Q30 82 44 92 Q40 74 40 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 60 Q90 82 76 92 Q80 74 80 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="60" cy="78" r="16" fill="${B}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M60 78 Q70 78 70 68 Q70 62 60 62 Q46 62 46 78 Q46 94 62 94 Q76 94 76 74" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".85"/>
      <circle cx="51" cy="56" r="10" fill="${ICING}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="69" cy="56" r="10" fill="${ICING}" stroke="${c.line}" stroke-width="2.2"/>
      ${ceye(51, 56, 4.4)}${ceye(69, 56, 4.4)}
      <path d="M60 62 l-4 5 h8 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${[46, 74].map((x) => `<path d="M${x} 98 l-4 5 M${x} 98 l0 6 M${x} 98 l4 5" stroke="${BEAK}" stroke-width="2.2" stroke-linecap="round"/>`).join("")}
    </g>`;
  },

  // ── Licorice Wyrm — a coiled ridged licorice worm, glossy segments, snug little head (t2)
  licoricewyrm: (c) => {
    const B = belly(c);
    const coil = "M60 96 Q30 96 30 76 Q30 58 56 58 Q78 58 78 72 Q78 84 60 84 Q46 84 46 74";
    return `
    ${floorShadow(60, 108, 28)}
    <g class="breathe">
      <ellipse cx="55" cy="94" rx="24" ry="6" fill="${c.shade}" opacity=".5"/>
      <path d="${coil}" fill="none" stroke="${c.line}" stroke-width="19" stroke-linecap="round"/>
      <path d="${coil}" fill="none" stroke="${c.body}" stroke-width="14.5" stroke-linecap="round"/>
      <path d="M30 76 q-2 -5 0 -9 M42 90 q4 3 9 3 M60 96 q6 -1 10 -4 M78 74 q4 -2 6 -6 M56 58 q0 -5 4 -8 M46 74 q-4 2 -6 6" stroke="${deepen(c.body, 0.3)}" stroke-width="2" stroke-linecap="round" opacity=".6"/>
      <path d="M40 88 Q42 84 50 84 M64 82 Q70 80 74 74" fill="none" stroke="${GLOSS}" stroke-width="2.4" stroke-linecap="round" opacity=".35"/>
      <path d="M42 68 Q40 52 52 50 Q64 52 62 66 Q54 74 42 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="51" cy="62" rx="7" ry="4.5" fill="${B}"/>
      <path d="M50 50 q-2 -6 3 -9 M50 50 q4 -3 9 -3" fill="none" stroke="${CHERRY}" stroke-width="1.5" stroke-linecap="round"/>
      ${ceye(48, 60, 3.4)}
      ${smile(51, 65, 2.4, INK)}
    </g>`;
  },

  // ── Taffy Cat — stretchy salt-water-taffy cat, twisted wrapper ends, glossy pull, cat face (t2)
  taffycat: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 27)}
    <g class="tail-wag">
      <path d="M82 96 Q98 92 100 78 L108 74 L104 82 L110 84 L102 88 Q98 100 82 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M46 44 L38 30 L56 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M74 44 L82 30 L64 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 110 C36 110 32 88 37 72 C40 60 46 52 60 50 C74 52 80 60 83 72 C88 88 84 110 60 110 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="19" ry="15" fill="${B}"/>
      <path d="M44 40 L36 34 L40 42 L32 44 L40 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 56 Q44 68 48 80" fill="none" stroke="${GLOSS}" stroke-width="3" stroke-linecap="round" opacity=".4"/>
      ${ceye(51, 64, 4)}${ceye(69, 64, 4)}
      <path d="M60 70 l-2.2 2.4 h4.4 Z" fill="${INK}"/>
      <path d="M60 72 v3 M60 75 q-4 3 -8 2 M60 75 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M46 66 h-11 M47 70 h-12 M74 66 h11 M73 70 h12" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>
    </g>`;
  },

  // ── Sherbet Bird — plump pastel songbird, soft banded belly, tiny wing & crest, big eyes (t1)
  sherbetbird: (c) => {
    const B = belly(c);
    const BEAK = "#f2a03b", LEG = "#e79a3a";
    return `
    ${floorShadow(60, 108, 22)}
    <g class="breathe">
      <path d="M58 34 Q50 26 56 22 Q62 24 62 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 62 Q34 44 52 40 Q60 30 70 40 Q86 44 84 66 Q84 90 60 92 Q38 90 38 70 Q37 66 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 70 Q60 66 74 70 Q72 84 60 86 Q48 84 46 70 Z" fill="${B}"/>
      <path d="M50 74 Q60 72 70 74 M52 80 Q60 79 68 80" fill="none" stroke="${tint(c.shade, 0.3)}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
      <path d="M78 60 Q92 62 90 78 Q80 76 76 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M70 46 L84 44 L74 52 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[54, 66].map((x) => `<path d="M${x} 90 l0 8 l-4 4 M${x} 98 l4 4 M${x} 98 l0 5" stroke="${LEG}" stroke-width="2" stroke-linecap="round" fill="none"/>`).join("")}
      ${ceye(59, 48, 4)}
      <circle cx="49" cy="60" r="4" fill="${CHERRY}" opacity=".22"/>
    </g>`;
  },

  // ── Fudge Bear — a blocky cut-fudge bear cub, square muzzle, glossy cut face, cozy sit (t2)
  fudgebear: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 28)}
    <g class="breathe">
      <rect x="33" y="30" width="18" height="18" rx="6" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="69" y="30" width="18" height="18" rx="6" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="38" y="30" width="8" height="8" rx="3" fill="${tint(c.body, 0.4)}" opacity=".6"/>
      <rect x="74" y="30" width="8" height="8" rx="3" fill="${tint(c.body, 0.4)}" opacity=".6"/>
      <path d="M36 46 Q36 38 44 38 L76 38 Q84 38 84 46 L84 96 Q84 104 76 104 L44 104 Q36 104 36 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 46 L60 42 L82 46" fill="none" stroke="${tint(c.body, 0.4)}" stroke-width="3" stroke-linecap="round" opacity=".5"/>
      <rect x="46" y="64" width="28" height="24" rx="5" fill="${B}"/>
      <rect x="52" y="72" width="16" height="14" rx="3" fill="${tint(c.body, 0.5)}"/>
      ${ceye(51, 58, 4)}${ceye(69, 58, 4)}
      <path d="M60 70 l-2.6 2.8 h5.2 Z" fill="${INK}"/>
      ${smile(60, 73, 3.2, INK)}
      <path d="M41 52 L41 96 M79 52 L79 96" stroke="${c.line}" stroke-width="1.4" opacity=".25"/>
    </g>`;
  },
};

export const ROSTER_CANDY = [
  { n: "Gummy Bear", e: "🍬", tier: 1, float: false },
  { n: "Candy Cane Serpent", e: "🍬", tier: 2, float: false },
  { n: "Cupcake Cat", e: "🧁", tier: 2, float: false },
  { n: "Donut Slime", e: "🍩", tier: 2, float: false },
  { n: "Cookie Golem", e: "🍬", tier: 2, float: false },
  { n: "Marshmallow Puff", e: "🍬", tier: 1, float: false },
  { n: "Lollipop Sprite", e: "🍭", tier: 1, float: false },
  { n: "Jelly Bean Bug", e: "🍬", tier: 1, float: false },
  { n: "Chocolate Hound", e: "🍬", tier: 2, float: false },
  { n: "Ice Cream Cone", e: "🍭", tier: 2, float: false },
  { n: "Popcorn Puff", e: "🍬", tier: 1, float: false },
  { n: "Pretzel Snake", e: "🍬", tier: 2, float: false },
  { n: "Waffle Turtle", e: "🍩", tier: 2, float: false },
  { n: "Bubblegum Blob", e: "🍬", tier: 1, float: false },
  { n: "Caramel Cub", e: "🍬", tier: 2, float: false },
  { n: "Peppermint Owl", e: "🍬", tier: 2, float: false },
  { n: "Licorice Wyrm", e: "🍬", tier: 2, float: false },
  { n: "Taffy Cat", e: "🍬", tier: 2, float: false },
  { n: "Sherbet Bird", e: "🍭", tier: 1, float: false },
  { n: "Fudge Bear", e: "🍬", tier: 2, float: false },
];
