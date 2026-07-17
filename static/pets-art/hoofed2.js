// pets-art/hoofed2.js — BESPOKE hand-drawn SVG art: MORE ANTELOPES & DEER (HOOFED2 batch, NADO Pets).
// Companion set to hoofed.js. Each entry: slug -> (c, v) => "<svg inner markup>" for viewBox 0 0 120 120,
// animal centred ~ (60,64), within x,y ∈ [8,114]. Palette-driven: c.body (main) · c.shade (accent/patches)
// · c.line (outline). ONE continuous silhouette: torso ellipse + tucked leg-rects + an overlapping neck
// tube + a head whose horns/antlers/ears root ON it — nothing floats. Two-tone via belly()/c.shade.
// Horns/antlers ivory (#f0e6d2); hooves dark; nose INK. Distinct signature per species (see comments).
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tail/ears <g class="tail-wag">.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const IVORY  = "#f0e6d2";   // pale ivory horns / antlers / tusks
const HORNSH = "#d9c9a3";   // shaded ivory (ring ticks)
const HOOF   = "#2e2a25";   // cloven hoof tips
const WHITE  = "#f4efe6";   // universal white markings (stripes/spots/rump ring/throat bib)

// ── shared building blocks (kept identical so the batch reads as one family) ──────────────────────
// paired ringed leg-rects tucked under the torso, dark hoof caps
const legs = (c, xl, xr, y, w, h) => ["", "s"].map((_, i) => {
  const x = i ? xr : xl;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${(w / 2.6).toFixed(1)}" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`
    + `<rect x="${x}" y="${y + h - 3.5}" width="${w}" height="3.5" rx="1.4" fill="${HOOF}"/>`;
}).join("");
// standard torso + pale two-tone belly
const torso = (c) => `<ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>`;
const uBelly = (c) => `<path d="M40 88 q20 7 40 0 q-4 6 -20 6 q-16 0 -20 -6 Z" fill="${belly(c)}"/>`;
// small flag tail with a dark/white tip
const wtail = (c, tip) => `<g class="tail-wag"><path d="M84 82 Q92 84 91 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="91" cy="96" r="2.4" fill="${tip || c.shade}"/></g>`;
// ears (root on the head, mirrored across x=60)
const ear = (c) => `<path d="M49 39 Q38 34 39 46 Q45 49 52 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M47 42 Q42 43 42 47" stroke="${c.shade}" stroke-width="2.2" fill="none" opacity=".6"/>`;
const ears = (c) => ear(c) + mirror(ear(c));
const bigEar = (c) => `<path d="M48 38 Q30 30 33 47 Q41 52 51 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M45 41 Q36 44 37 49" stroke="${c.shade}" stroke-width="2.4" fill="none" opacity=".6"/>`;
const bigEars = (c) => bigEar(c) + mirror(bigEar(c));
// standard antelope/deer 3-4 face (head + muzzle + nose + eyes). cface = bigger cute eyes.
const face = (c) => `<path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`
  + `<path d="M54 60 q6 4 12 0 Q60 66 54 60 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>`
  + eyes(53, 67, 52, 2.6, eyeInk(c));
const cface = (c) => `<path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`
  + `<path d="M54 60 q6 4 12 0 Q60 66 54 60 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.8" ry="2" fill="${INK}"/>`
  + eyes(53, 67, 51, 3.2, eyeInk(c));
// standard neck tube (body -> under head)
const neck = (c) => tube("M50 80 Q46 58 52 44", c.body, c.line, 8);
// horn helpers: plain ivory pair, or ringed pair (with tick marks)
const horns = (d, w) => { const h = `<path d="${d}" fill="none" stroke="${IVORY}" stroke-width="${w}" stroke-linecap="round"/>`; return h + mirror(h); };
const ringed = (d, ticks, w) => {
  const horn = `<path d="${d}" fill="none" stroke="${IVORY}" stroke-width="${w}" stroke-linecap="round"/>`;
  const tk = ticks.map(([x, y]) => `<path d="M${x - 3} ${y} L${x + 3} ${y}" stroke="${HORNSH}" stroke-width="1.2"/>`).join("");
  return horn + tk + mirror(horn + tk);
};
const spots = (pts, r, col) => pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}" opacity=".85"/>`).join("");

export const ART_HOOFED2 = {
  // ── Nyala — spiral lyre horns (ivory white tips), thin white body stripes, shaggy belly fringe (t3) ─
  nyala: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c, WHITE)}
    <g class="breathe">${torso(c)}
      <g stroke="${WHITE}" stroke-width="2" opacity=".85" stroke-linecap="round"><path d="M46 72 q-1 11 0 21 M55 71 q-1 12 0 23 M64 71 q1 11 0 22 M73 73 q1 10 0 18"/></g>
      ${uBelly(c)}
      ${Array.from({ length: 7 }).map((_, i) => `<path d="M${46 + i * 4.5} 91 l1.6 6 l1.6 -6 Z" fill="${c.shade}" opacity=".7"/>`).join("")}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      ${ringed("M54 34 Q49 18 55 6 Q56 3 59 6", [[52, 28], [51, 20], [52, 12]], 3.2)}
      <circle cx="59" cy="6" r="1.8" fill="${WHITE}"/>${mirror(`<circle cx="59" cy="6" r="1.8" fill="${WHITE}"/>`)}
      ${ears(c)}${face(c)}</g>`,

  // ── Sitatunga — swamp antelope: slight open-spiral horns, shaggy coat, big SPLAYED elongated hooves (t2) ─
  sitatunga: (c) => `
    ${floorShadow(60, 111, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      ${Array.from({ length: 6 }).map((_, i) => `<path d="M${46 + i * 5} 76 q-2 8 0 14" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/>`).join("")}
      ${uBelly(c)}
      ${["", "s"].map((_, i) => { const x = i ? 70 : 48; return `<rect x="${x}" y="94" width="7" height="13" rx="2.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><path d="M${x - 2} 107 L${x + 3.5} 116 L${x + 9} 107 Z" fill="${HOOF}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/><path d="M${x + 3.5} 107 L${x + 3.5} 116" stroke="${c.line}" stroke-width="1"/>`; }).join("")}</g>
    ${neck(c)}
    <g class="head-tilt">
      ${horns("M54 36 Q60 24 55 12 Q52 8 56 6", 3)}
      ${ears(c)}${face(c)}</g>`,

  // ── Waterbuck — long forward-sweeping ringed horns, bold WHITE RING on the rump (t2) ──────────────
  waterbuck: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      ${uBelly(c)}
      <circle cx="76" cy="83" r="9" fill="none" stroke="${WHITE}" stroke-width="2.6"/>
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      ${ringed("M55 34 Q62 16 54 4 Q52 1 50 5", [[53, 28], [56, 20], [55, 12]], 3.4)}
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Lechwe — ringed lyre horns swept back then hooking up, dark front-leg fronts, golden marsh coat (t2) ─
  lechwe: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}
      <rect x="48.5" y="95" width="2.4" height="14" rx="1" fill="${INK}" opacity=".45"/><rect x="70.5" y="95" width="2.4" height="14" rx="1" fill="${INK}" opacity=".45"/></g>
    ${neck(c)}
    <g class="head-tilt">
      ${ringed("M53 34 Q43 22 49 8 Q51 3 57 9", [[51, 28], [47, 20], [50, 12]], 3.2)}
      ${ears(c)}${face(c)}</g>`,

  // ── Topi — reddish coat with dark blue-black shoulder & thigh patches, short ringed lyre horns (t2) ─
  topi: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      <ellipse cx="45" cy="82" rx="7" ry="9" fill="${deepen(c.body, .45)}" opacity=".7"/>
      <ellipse cx="75" cy="86" rx="7" ry="8" fill="${deepen(c.body, .45)}" opacity=".7"/>
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}
      <rect x="48.5" y="96" width="7" height="8" rx="2" fill="${deepen(c.body, .45)}" opacity=".55"/><rect x="70.5" y="96" width="7" height="8" rx="2" fill="${deepen(c.body, .45)}" opacity=".55"/></g>
    ${neck(c)}
    <g class="head-tilt">
      ${ringed("M54 34 Q48 22 55 10 Q57 7 59 10", [[52, 28], [52, 20], [54, 13]], 3)}
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 46 Q50 58 60 66 Q70 58 68 46 Q60 42 52 46 Z" fill="${deepen(c.body, .4)}" opacity=".55"/>
      <ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Hartebeest — very long narrow face, Z-shaped bracket horns on a tall bony pedicle (t2) ─────────
  hartebeest: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      <path d="M56 40 L56 30" stroke="${c.body}" stroke-width="6" stroke-linecap="round"/><path d="M64 40 L64 30" stroke="${c.body}" stroke-width="6" stroke-linecap="round"/>
      ${horns("M57 30 Q50 24 55 17 Q60 13 57 7", 3.2)}
      ${ears(c)}
      <path d="M53 38 Q51 68 60 78 Q69 68 67 38 Q60 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 72 q5 4 10 0 Q60 78 55 72 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="74" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(54, 66, 50, 2.6, eyeInk(c))}</g>`,

  // ── Blackbuck — dramatic long CORKSCREW spiral horns, dark back / white belly & eye-ring (t3) ──────
  blackbuck: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c)}
    <g class="breathe">${torso(c)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      ${horns("M56 34 Q49 30 55 26 Q61 22 54 18 Q48 14 55 10 Q61 6 56 3", 3.2)}
      ${[[53, 30], [56, 24], [52, 18], [56, 12], [53, 7]].map(([x, y]) => `<path d="M${x - 2.5} ${y} L${x + 2.5} ${y}" stroke="${HORNSH}" stroke-width="1.1"/>`).join("")}
      ${mirror(`${[[53, 30], [56, 24], [52, 18], [56, 12], [53, 7]].map(([x, y]) => `<path d="M${x - 2.5} ${y} L${x + 2.5} ${y}" stroke="${HORNSH}" stroke-width="1.1"/>`).join("")}`)}
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="53" cy="52" rx="4" ry="4.4" fill="${WHITE}" opacity=".9"/>${mirror(`<ellipse cx="53" cy="52" rx="4" ry="4.4" fill="${WHITE}" opacity=".9"/>`)}
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Nilgai — hulking blue-grey bull, sloping back, short conical horns, white throat bib & cheeks (t2) ─
  nilgai: (c) => `
    ${floorShadow(60, 111, 30)}
    ${wtail(c)}
    <g class="breathe">
      <path d="M36 78 Q40 60 60 60 Q82 64 85 88 Q83 95 58 95 Q36 93 36 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M42 90 q20 6 40 0 q-4 6 -20 6 q-16 0 -20 -6 Z" fill="${belly(c)}"/>
      ${legs(c, 46, 72, 94, 8, 17)}</g>
    ${tube("M48 76 Q46 58 52 44", c.body, c.line, 9)}
    <path d="M50 66 Q54 82 60 84 Q58 72 56 60 Z" fill="${WHITE}"/>
    <g class="head-tilt">
      ${horns("M56 38 L54 27", 3.2)}
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="55" cy="58" r="1.8" fill="${WHITE}"/><circle cx="65" cy="58" r="1.8" fill="${WHITE}"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Chital — rufous SPOTTED axis deer, three-tine lyre antlers, white throat (t2) ────────────────
  chital: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c, WHITE)}
    <g class="breathe">${torso(c)}
      ${spots([[47, 78], [55, 76], [63, 77], [71, 79], [50, 85], [58, 84], [66, 85], [74, 85], [44, 84]], 1.9, WHITE)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      <g class="tail-wag">${horns("M56 40 Q52 22 58 8 M55 26 Q48 20 44 18 M57 14 Q51 8 47 8", 2.8)}</g>
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Sambar — big dark forest deer, rugged sturdy three-tine antlers, shaggy neck mane (t2) ────────
  sambar: (c) => `
    ${floorShadow(60, 110, 30)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="60" cy="84" rx="26" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${uBelly(c)}
      ${legs(c, 47, 71, 94, 8, 16)}</g>
    ${tube("M50 80 Q45 58 52 44", c.body, c.line, 9)}
    ${Array.from({ length: 5 }).map((_, i) => `<path d="M${47 + i * 1.6} ${74 - i * 6} q-5 2 -6 5" stroke="${c.shade}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`).join("")}
    <g class="head-tilt">
      <g class="tail-wag">${horns("M56 40 Q50 24 58 12 M54 28 Q47 24 43 26 M57 18 Q52 12 47 14", 3.4)}</g>
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="3.2" ry="2.4" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Muntjac — tiny "barking deer": short antlers on long furry pedicles, downward TUSKS, V forehead (t1) ─
  muntjac: (c) => `
    ${floorShadow(60, 111, 25)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="60" cy="87" rx="21" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 90 q18 6 36 0 q-4 5 -18 5 q-14 0 -18 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 49, 68, 97, 6, 13)}</g>
    ${tube("M51 83 Q48 62 54 46", c.body, c.line, 7)}
    <g class="head-tilt">
      <path d="M56 44 L54 32" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/><path d="M64 44 L66 32" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>
      ${horns("M54 33 Q52 27 56 25", 2.4)}
      ${ears(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 46 L58 55 M66 46 L62 55" stroke="${c.shade}" stroke-width="1.6" fill="none"/>
      <path d="M56 65 q-1 4 -2.5 6.5" fill="none" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/>${mirror(`<path d="M56 65 q-1 4 -2.5 6.5" fill="none" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/>`)}
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 51, 2.8, eyeInk(c))}</g>`,

  // ── Roe Deer — small, short rough 3-point pearled antlers, white chin, black nose (t1) ────────────
  roedeer: (c) => `
    ${floorShadow(60, 110, 26)}
    ${wtail(c, WHITE)}
    <g class="breathe"><ellipse cx="60" cy="85" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M41 89 q19 6 38 0 q-4 5 -19 5 q-15 0 -19 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 48, 69, 95, 6, 15)}</g>
    ${tube("M50 81 Q46 60 53 46", c.body, c.line, 7.5)}
    <g class="head-tilt">
      ${horns("M56 42 Q54 30 57 21 M56 30 Q51 26 48 24 M57 23 Q52 19 49 19", 2.6)}
      <circle cx="56.5" cy="22" r="1.2" fill="${IVORY}"/>${mirror(`<circle cx="56.5" cy="22" r="1.2" fill="${IVORY}"/>`)}
      ${ears(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.4" fill="${INK}"/>
      ${eyes(53, 67, 51, 2.8, eyeInk(c))}</g>`,

  // ── Fallow Deer — broad PALMATE (paddle) antlers with edge tines, dappled white spots (t2) ────────
  fallowdeer: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c, WHITE)}
    <g class="breathe">${torso(c)}
      ${spots([[48, 77], [56, 76], [64, 77], [72, 78], [51, 84], [59, 84], [67, 84], [45, 83]], 1.9, WHITE)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      <g class="tail-wag">
        <path d="M56 40 Q50 26 47 12 Q57 8 63 18 Q61 30 59 40 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
        <path d="M47 12 l-4 -3 M49 18 l-6 -2 M52 25 l-7 -1" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/>
        ${mirror(`<path d="M56 40 Q50 26 47 12 Q57 8 63 18 Q61 30 59 40 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/><path d="M47 12 l-4 -3 M49 18 l-6 -2 M52 25 l-7 -1" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/>`)}
      </g>
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Sika Deer — spotted in rows, branching antlers, dark dorsal stripe, bright white rump (t2) ─────
  sikadeer: (c) => `
    ${floorShadow(60, 110, 28)}
    ${wtail(c, WHITE)}
    <g class="breathe">${torso(c)}
      <path d="M39 76 Q60 71 81 78" stroke="${deepen(c.body, .4)}" stroke-width="2.4" fill="none" opacity=".7"/>
      <ellipse cx="80" cy="82" rx="6" ry="8" fill="${WHITE}" opacity=".85"/>
      ${spots([[48, 79], [56, 78], [64, 79], [50, 86], [58, 85], [66, 86]], 1.7, WHITE)}
      ${uBelly(c)}
      ${legs(c, 48, 70, 94, 7, 16)}</g>
    ${neck(c)}
    <g class="head-tilt">
      <g class="tail-wag">${horns("M56 40 Q53 22 60 10 M55 24 Q49 18 45 20 M58 14 Q52 9 48 11", 2.8)}</g>
      ${ears(c)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${WHITE}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}</g>`,

  // ── Southern Pudu — world's smallest deer: round stubby body, short legs, tiny spike antlers (t1) ──
  southernpudu: (c) => `
    ${floorShadow(60, 111, 24)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="60" cy="88" rx="20" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M43 92 q17 6 34 0 q-4 5 -17 5 q-13 0 -17 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 49, 68, 99, 6, 11)}</g>
    ${tube("M51 85 Q49 64 54 47", c.body, c.line, 7.5)}
    <g class="head-tilt">
      ${horns("M56 42 L55 33", 2.6)}
      ${ears(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 51, 3.2, eyeInk(c))}</g>`,

  // ── Red Brocket — small hunched forest deer: simple spike antlers, strongly arched back (t1) ───────
  redbrocket: (c) => `
    ${floorShadow(60, 110, 26)}
    ${wtail(c)}
    <g class="breathe">
      <path d="M40 88 Q44 60 60 58 Q76 60 80 88 Q78 94 60 94 Q42 94 40 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M42 90 q18 6 36 0 q-4 5 -18 5 q-14 0 -18 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 48, 69, 94, 6, 16)}</g>
    ${tube("M49 84 Q46 62 53 46", c.body, c.line, 7.5)}
    <g class="head-tilt">
      ${horns("M56 42 L54 27", 2.8)}
      ${ears(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.9" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 51, 2.7, eyeInk(c))}</g>`,

  // ── Blue Duiker — tiny, strongly ARCHED back, minute horns between the ears, forehead crest tuft (t1) ─
  blueduiker: (c) => `
    ${floorShadow(60, 111, 24)}
    ${wtail(c)}
    <g class="breathe">
      <path d="M42 91 Q46 60 60 57 Q74 60 78 91 Q76 95 60 95 Q44 95 42 91 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 92 q16 6 32 0 q-4 5 -16 5 q-12 0 -16 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 50, 67, 96, 5, 15)}</g>
    ${tube("M50 86 Q48 66 54 48", c.body, c.line, 7)}
    <g class="head-tilt">
      ${horns("M57 42 L56 33", 2.2)}
      ${pom(60, 36, 4, c.shade, c.line, 7, 1.4)}
      ${bigEars(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 51, 3.2, eyeInk(c))}</g>`,

  // ── Klipspringer — rock-hopper on the TIPS of its hooves, rounded speckled coat, short spike horns (t2) ─
  klipspringer: (c) => `
    ${floorShadow(60, 112, 22)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="60" cy="82" rx="23" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${spots([[46, 74], [54, 72], [62, 73], [70, 75], [50, 82], [58, 81], [66, 82], [74, 82], [48, 88], [60, 88], [72, 88]], 1.3, c.shade)}
      ${uBelly(c)}
      ${["", "s"].map((_, i) => { const x = i ? 68 : 50; return `<path d="M${x} 92 L${x + 1} 108" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/><path d="M${x} 92 L${x + 1} 108" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/><path d="M${x - 1.5} 108 L${x + 1} 114 L${x + 3.5} 108 Z" fill="${HOOF}" stroke="${c.line}" stroke-width="1"/>`; }).join("")}</g>
    ${tube("M50 78 Q47 60 53 46", c.body, c.line, 7.5)}
    <g class="head-tilt">
      ${horns("M56 42 L55 29", 2.8)}
      ${ears(c)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.7, eyeInk(c))}</g>`,

  // ── Steenbok — small, ENORMOUS upright ears, short straight vertical spike horns, huge eyes (t1) ───
  steenbok: (c) => `
    ${floorShadow(60, 110, 26)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="60" cy="85" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M41 89 q19 6 38 0 q-4 5 -19 5 q-15 0 -19 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 48, 69, 95, 6, 15)}</g>
    ${tube("M50 81 Q47 60 53 46", c.body, c.line, 7.5)}
    <g class="head-tilt">
      ${horns("M56 42 L55 26", 2.8)}
      <path d="M50 40 Q28 30 30 50 Q40 56 53 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M46 43 Q35 46 37 52" stroke="${c.shade}" stroke-width="2.6" fill="none" opacity=".6"/>
      ${mirror(`<path d="M50 40 Q28 30 30 50 Q40 56 53 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M46 43 Q35 46 37 52" stroke="${c.shade}" stroke-width="2.6" fill="none" opacity=".6"/>`)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 61 q5 3 10 0 Q60 66 55 61 Z" fill="${c.shade}"/><ellipse cx="60" cy="62" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 51, 3.4, eyeInk(c))}</g>`,

  // ── Gerenuk — the "giraffe-necked" antelope: very long slender neck, small head, short S-hook horns (t2) ─
  gerenuk: (c) => `
    ${floorShadow(60, 111, 26)}
    ${wtail(c)}
    <g class="breathe"><ellipse cx="62" cy="88" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 92 q18 6 36 0 q-4 5 -18 5 q-14 0 -18 -5 Z" fill="${belly(c)}"/>
      ${legs(c, 50, 72, 98, 6, 13)}</g>
    ${tube("M54 86 Q42 56 52 30", c.body, c.line, 8)}
    <g class="head-tilt">
      ${horns("M55 26 Q49 20 54 14 Q57 11 55 8", 2.8)}
      <path d="M50 25 Q41 21 42 31 Q47 34 53 29 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>${mirror(`<path d="M50 25 Q41 21 42 31 Q47 34 53 29 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <path d="M53 26 Q51 40 60 48 Q69 40 67 26 Q60 21 53 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 44 q5 3 10 0 Q60 49 55 44 Z" fill="${WHITE}"/><ellipse cx="60" cy="45" rx="2.8" ry="2.1" fill="${INK}"/>
      <ellipse cx="54" cy="34" rx="3.6" ry="3" fill="${WHITE}" opacity=".7"/>${mirror(`<ellipse cx="54" cy="34" rx="3.6" ry="3" fill="${WHITE}" opacity=".7"/>`)}
      ${eyes(54, 66, 35, 2.6, eyeInk(c))}</g>`,
};

// roster metadata — every `n` slugifies to an ART_HOOFED2 key above (1:1)
export const ROSTER_HOOFED2 = [
  { n: "Nyala",          e: "🦌", tier: 3, float: false },
  { n: "Sitatunga",      e: "🦌", tier: 2, float: false },
  { n: "Waterbuck",      e: "🦌", tier: 2, float: false },
  { n: "Lechwe",         e: "🦌", tier: 2, float: false },
  { n: "Topi",           e: "🦌", tier: 2, float: false },
  { n: "Hartebeest",     e: "🦌", tier: 2, float: false },
  { n: "Blackbuck",      e: "🦌", tier: 3, float: false },
  { n: "Nilgai",         e: "🦌", tier: 2, float: false },
  { n: "Chital",         e: "🦌", tier: 2, float: false },
  { n: "Sambar",         e: "🦌", tier: 2, float: false },
  { n: "Muntjac",        e: "🦌", tier: 1, float: false },
  { n: "Roe Deer",       e: "🦌", tier: 1, float: false },
  { n: "Fallow Deer",    e: "🦌", tier: 2, float: false },
  { n: "Sika Deer",      e: "🦌", tier: 2, float: false },
  { n: "Southern Pudu",  e: "🦌", tier: 1, float: false },
  { n: "Red Brocket",    e: "🦌", tier: 1, float: false },
  { n: "Blue Duiker",    e: "🦌", tier: 1, float: false },
  { n: "Klipspringer",   e: "🦌", tier: 2, float: false },
  { n: "Steenbok",       e: "🦌", tier: 1, float: false },
  { n: "Gerenuk",        e: "🦌", tier: 2, float: false },
];
