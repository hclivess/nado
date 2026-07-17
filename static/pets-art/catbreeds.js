// catbreeds.js — BESPOKE hand-drawn SVG art for DOMESTIC CAT BREEDS (NADO Pets).
// HOUSE STYLE (pets-draw method): ONE continuous body+head+ears silhouette per cat, two-tone shading
// (belly/deepen), big glossy `ceye` faces, appendages tucked/overlapping, grounded with floorShadow.
// Coat comes ONLY from `c` {body, shade, line}; extra tones via belly()/tint()/deepen(). No hardcoded
// species colours except INK, #fff (gloves/blaze) and small breed EYE-colour accents (iris tone only).
// Every ROSTER `n` slugifies 1:1 to an ART key. All float:false (grounded quadrupeds).
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes } from "../pets-draw.js";

const WHITE = "#ffffff";
// breed eye-colour accents (iris tone only — not a coat colour)
const BLUE = "#6ea3d8", GREEN = "#89b45c", GOLD = "#e0b24a", COPPER = "#e0902f", AMBER = "#cf9a34";

// ── shared drawing helpers ───────────────────────────────────────────────────
// colour-iris cute eye (iris ring + dark pupil + catchlight) for blue/green/gold-eyed breeds
const ceyeC = (x, y, r, iris) =>
  `<g class="blink"><ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * 1.15).toFixed(1)}" fill="${iris}"/>` +
  `<ellipse cx="${x}" cy="${y}" rx="${(r * 0.5).toFixed(1)}" ry="${(r * 0.95).toFixed(1)}" fill="${INK}"/>` +
  `<circle cx="${(x - r * 0.34).toFixed(1)}" cy="${(y - r * 0.46).toFixed(1)}" r="${(r * 0.36).toFixed(1)}" fill="#fff"/></g>`;
const eyesOf = (xL, xR, y, r, iris) => iris ? ceyeC(xL, y, r, iris) + ceyeC(xR, y, r, iris) : ceye(xL, y, r) + ceye(xR, y, r);

// small ink nose + gentle mouth
const muzz = (c, x = 60, y = 75) =>
  `<path d="M${x} ${y} l-3.2 3 h6.4 Z" fill="${INK}"/>` +
  `<path d="M${x} ${y + 3} v3 M${x} ${y + 6} q-4 3 -8 2 M${x} ${y + 6} q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>`;
// upturned "smiling" mouth (Chartreux)
const smileMuzz = (c, x = 60, y = 75) =>
  `<path d="M${x} ${y} l-3.2 3 h6.4 Z" fill="${INK}"/>` +
  `<path d="M${x} ${y + 3} v3 M${x} ${y + 6} q-5 5 -9 1 M${x} ${y + 6} q5 5 9 1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
const whisk = (c) => `<path d="M35 69 h-16 M36 74 h-17 M85 69 h16 M84 74 h17" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>`;

// inner-ear triangle: shrink the ear's 3 corners toward its centroid, fill darker
const inEar = (ex, ey, cx, cy, bx, by, fill, t = 0.32) => {
  const gx = (ex + cx + bx) / 3, gy = (ey + cy + by) / 3;
  const P = (x, y) => `${(x + (gx - x) * t).toFixed(1)} ${(y + (gy - y) * t).toFixed(1)}`;
  return `<path d="M${P(ex, ey)} L${P(cx, cy)} L${P(bx, by)} Z" fill="${fill}"/>`;
};

// ONE-path sitting-cat silhouette (body + head + integrated triangular ears). Symmetric about x=60.
const sit = (c, o = {}) => {
  const f = o.flare ?? 0,
    eLx = o.eLx ?? 33, eLy = o.eLy ?? 24, eRx = o.eRx ?? 87, eRy = o.eRy ?? 24,
    biL = o.biL ?? 54, biR = o.biR ?? 66, biY = o.biY ?? 43, dip = o.dip ?? 39,
    chL = o.chL ?? 41, chR = o.chR ?? 79, chY = o.chY ?? 49,
    body = o.body ?? c.body;
  return `<path d="M60 112 C${30 - f} 112 ${26 - f} 92 ${31 - f} 72 C${33 - f} 60 ${36 - f} 54 ${chL} ${chY} L${eLx} ${eLy} L${biL} ${biY} Q60 ${dip} ${biR} ${biY} L${eRx} ${eRy} L${chR} ${chY} C${84 + f} 54 ${87 + f} 60 ${89 + f} 72 C${94 + f} 92 ${90 + f} 112 60 112 Z" fill="${body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
};
// paired inner ears for a sit() opts object
const earsIn = (o, fill) => {
  const eLx = o.eLx ?? 33, eLy = o.eLy ?? 24, chL = o.chL ?? 41, chY = o.chY ?? 49, biL = o.biL ?? 54, biY = o.biY ?? 43;
  const L = inEar(eLx, eLy, chL, chY, biL, biY, fill);
  return L + mirror(L);
};

// pale muzzle/cheek patch underlying the eyes (keeps eyes visible on dark coats)
const patch = (c, cy = 73, rx = 18, ry = 13) => `<ellipse cx="60" cy="${cy}" rx="${rx}" ry="${ry}" fill="${belly(c)}"/>`;
// standard sitting face (eyes + muzzle + whiskers) — pass iris for coloured eyes
const face = (c, o = {}) =>
  `${eyesOf(o.eL ?? 51, o.eR ?? 69, o.eY ?? 66, o.er ?? 4.2, o.iris ?? null)}${(o.smile ? smileMuzz : muzz)(c, 60, o.mzY ?? 75)}${o.noWhisk ? "" : whisk(c)}`;

// pattern / texture helpers
const spot = (c, x, y, r) => `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * 0.84).toFixed(1)}" fill="${c.shade}"/>`;
const rosette = (c, x, y, r) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${c.shade}" stroke-width="1.7"/>` +
  `<circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y + r * 0.25).toFixed(1)}" r="${(r * 0.3).toFixed(1)}" fill="${c.shade}"/>`;
const tick = (c, x, y) => `<path d="M${x} ${y} l1.4 3.2" stroke="${c.shade}" stroke-width="1.1" stroke-linecap="round" opacity=".6"/>`;
const foreM = (c, y = 55) => `<path d="M49 ${y + 3} Q51 ${y - 4} 54 ${y} Q57 ${y + 4} 60 ${y - 1} Q63 ${y + 4} 66 ${y} Q69 ${y - 4} 71 ${y + 3}" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".85"/>`;
const stripes = (c, ys = [90, 98, 106]) => ys.map((y) => `<path d="M40 ${y} q20 6 40 0" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round" opacity=".5"/>`).join("");
const waves = (c, ys) => ys.map((y) => `<path d="M42 ${y} q6 -4 12 0 t12 0 t12 0" fill="none" stroke="${c.shade}" stroke-width="1.5" stroke-linecap="round" opacity=".6"/>`).join("");
const tuft = (c, x, y) => `<path d="M${x} ${y} l-1.5 -11 l5.5 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`;
// fluffy scalloped chest bib (long-hair signal)
const bib = (c) => `<path d="M45 85 Q49 93 46 100 Q52 96 54 103 Q60 96 60 105 Q60 96 66 103 Q68 96 74 100 Q71 93 75 85 Q60 98 45 85 Z" fill="${belly(c)}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`;

// tails (rooted inside the body flank so no seam floats)
const tailCurl = (c, fill) => `<g class="tail-wag"><path d="M80 98 Q104 94 99 74 Q97 63 86 66 Q95 72 88 84 Q82 92 74 91 Z" fill="${fill}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>`;
const tailThin = (c) => `<g class="tail-wag"><path d="M80 96 Q100 92 98 76 Q97 68 90 70 Q95 76 90 84 Q85 90 78 89 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>`;
const tailBushy = (c) => `<g class="tail-wag"><path d="M78 100 Q108 98 107 66 Q106 50 90 54 Q102 62 97 82 Q91 97 74 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M99 71 q6 -1 7 -7 M95 84 q6 0 8 -6" stroke="${c.shade}" stroke-width="3" fill="none" stroke-linecap="round" opacity=".65"/></g>`;
const tailPoint = (c) => `<g class="tail-wag"><path d="M78 100 Q108 98 107 66 Q106 50 90 54 Q102 62 97 82 Q91 97 74 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M105 55 Q112 64 105 78 Q99 68 90 64 Q99 59 105 55 Z" fill="${c.shade}"/></g>`;
const tailPlume = (c) => `<g class="tail-wag"><path d="M76 98 Q108 96 109 60 Q110 44 92 49 Q105 57 100 80 Q94 96 72 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M100 58 Q106 70 101 83 Q96 72 89 68 Q97 63 100 58 Z" fill="${belly(c)}" opacity=".85"/></g>`;

export const ART_CATBREEDS = {
  // ── Maine Coon — big & boxy, LYNX-TIP tufted ears, heavy ruff, banded bushy tail, tabby ──
  mainecoon: (c) => {
    const o = { flare: 3, eLx: 31, eLy: 18, eRx: 89, eRy: 18, biL: 53, biR: 67, chL: 39, chY: 50, dip: 40 };
    return `
    ${floorShadow(60, 111, 33)}
    ${tailBushy(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.16))}
      ${tuft(c, 31, 18)}${mirror(tuft(c, 31, 18))}
      <path d="M37 61 q-4 9 3 17 q3 -8 5 -14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>${mirror(`<path d="M37 61 q-4 9 3 17 q3 -8 5 -14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      ${stripes(c, [92, 100, 108])}
      <ellipse cx="60" cy="94" rx="18" ry="10" fill="${belly(c)}"/>
      ${patch(c, 73, 19, 13)}
      ${foreM(c, 55)}
      ${face(c, {})}
    </g>`;
  },

  // ── Bengal — sleek athletic, OPEN ROSETTE spots, gold eyes, ringed tail ──
  bengal: (c) => {
    const o = { flare: -1, eLx: 35, eLy: 23, eRx: 85, eRy: 23, chL: 42 };
    return `
    ${floorShadow(60, 111, 28)}
    <g class="tail-wag"><path d="M80 98 Q104 94 99 74 Q97 63 86 66 Q95 72 88 84 Q82 92 74 91 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><g stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".8"><path d="M97 72 h6 M93 82 h6"/></g></g>
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      ${patch(c, 73, 18, 13)}
      ${foreM(c, 55)}
      ${rosette(c, 43, 89, 4)}${rosette(c, 56, 93, 4)}${rosette(c, 69, 93, 4)}${rosette(c, 80, 88, 3.6)}${rosette(c, 49, 104, 3.6)}${rosette(c, 72, 104, 3.6)}
      ${face(c, { iris: GOLD })}
    </g>`;
  },

  // ── Sphynx — hairless, HUGE bat ears, wrinkled skin, pot-belly, no whiskers ──
  sphynx: (c) => {
    const o = { flare: 2, eLx: 27, eLy: 13, eRx: 93, eRy: 13, biL: 52, biR: 68, chL: 37, chY: 48, dip: 40 };
    const W = deepen(c.body, 0.18);
    return `
    ${floorShadow(60, 111, 30)}
    ${tailThin(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.12))}
      ${patch(c, 74, 16, 12)}
      <path d="M48 52 q12 -3 24 0 M49 57 q11 -3 22 0 M52 61 q8 -2 16 0" fill="none" stroke="${W}" stroke-width="1.5" stroke-linecap="round" opacity=".8"/>
      <path d="M36 82 q6 4 1 10 M84 82 q-6 4 -1 10 M43 91 q17 5 34 0 M46 97 q14 4 28 0" fill="none" stroke="${W}" stroke-width="1.4" stroke-linecap="round" opacity=".65"/>
      ${face(c, { er: 4.7, noWhisk: true })}
    </g>`;
  },

  // ── Ragdoll — big & fluffy, dark COLOURPOINT mask/ears/tail, blue eyes ──
  ragdoll: (c) => {
    const o = { flare: 2, eLx: 33, eLy: 20, eRx: 87, eRy: 20, chL: 40 };
    return `
    ${floorShadow(60, 111, 31)}
    ${tailPoint(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.25), )}
      <path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".85"/>${mirror(`<path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".85"/>`)}
      ${bib(c)}
      ${patch(c, 72, 20, 15)}
      <path d="M60 60 Q46 65 48 80 Q60 90 72 80 Q74 65 60 60 Z" fill="${c.shade}" opacity=".8"/>
      <ellipse cx="60" cy="74" rx="9" ry="7" fill="${belly(c)}" opacity=".9"/>
      ${face(c, { iris: BLUE })}
    </g>`;
  },

  // ── Russian Blue — sleek plush, refined build, SHEEN highlight, vivid green eyes ──
  russianblue: (c) => {
    const o = { flare: -2, eLx: 34, eLy: 22, eRx: 86, eRy: 22, chL: 42 };
    return `
    ${floorShadow(60, 111, 27)}
    ${tailCurl(c, c.body)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      <ellipse cx="60" cy="58" rx="19" ry="9" fill="${tint(c.body, 0.22)}" opacity=".55"/>
      <ellipse cx="60" cy="94" rx="17" ry="9" fill="${tint(c.body, 0.16)}" opacity=".4"/>
      ${patch(c, 73, 17, 12)}
      ${face(c, { iris: GREEN })}
    </g>`;
  },

  // ── Scottish Fold — round owl-head, FOLDED forward ears (no points), big eyes ──
  scottishfold: (c) => {
    const o = { flare: 3, eLx: 45, eLy: 42, eRx: 75, eRy: 42, biL: 53, biR: 67, biY: 45, dip: 45, chL: 43, chY: 50 };
    const foldL = `<path d="M40 45 Q37 33 49 37 Q53 44 47 51 Q42 50 40 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M43 41 Q47 41 47 47" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".6"/><path d="M44 44 Q47 44 47 49 Q43 48 44 44 Z" fill="${deepen(c.body, 0.14)}"/>`;
    return `
    ${floorShadow(60, 111, 30)}
    ${tailCurl(c, c.body)}
    <g class="breathe">
      ${sit(c, o)}
      ${foldL}${mirror(foldL)}
      ${patch(c, 73, 19, 13)}
      ${face(c, { er: 4.7, iris: COPPER })}
    </g>`;
  },

  // ── Abyssinian — lean & long-legged (standing), big ears, fine TICKED coat, almond eyes ──
  abyssinian: (c) => {
    const legs = [45, 54, 66, 75].map((x) => `<rect x="${x}" y="84" width="6" height="24" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("");
    const body = `<path d="M60 90 C43 90 39 76 40 62 C41 54 44 49 49 46 L40 18 L55 42 Q60 38 65 42 L80 18 L71 46 C76 49 79 54 80 62 C81 76 77 90 60 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
    const ticks = [[46, 66], [54, 62], [62, 62], [70, 66], [44, 76], [52, 72], [60, 70], [68, 72], [76, 76], [50, 84], [60, 82], [70, 84]].map(([x, y]) => tick(c, x, y)).join("");
    return `
    ${floorShadow(60, 111, 26)}
    <g class="tail-wag"><path d="M78 90 Q104 88 106 60 Q107 46 96 50 Q102 60 98 78 Q92 90 74 87 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M103 54 Q108 62 104 74 Z" fill="${c.shade}" opacity=".7"/></g>
    <g class="breathe">
      ${legs}
      ${body}
      ${inEar(40, 18, 49, 46, 55, 42, c.shade)}${mirror(inEar(40, 18, 49, 46, 55, 42, c.shade))}
      ${ticks}
      <ellipse cx="60" cy="60" rx="15" ry="11" fill="${belly(c)}"/>
      ${foreM(c, 52)}
      ${eyesOf(53, 67, 60, 4, INK)}${muzz(c, 60, 68)}${whisk(c)}
    </g>`;
  },

  // ── British Shorthair — very ROUND & chunky, small wide-set ears, jowly cheeks, copper eyes ──
  britishshorthair: (c) => {
    const o = { flare: 6, eLx: 38, eLy: 26, eRx: 82, eRy: 26, biL: 52, biR: 68, biY: 44, dip: 44, chL: 44, chY: 52 };
    return `
    ${floorShadow(60, 111, 34)}
    ${tailCurl(c, c.body)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      <ellipse cx="45" cy="72" rx="9" ry="8" fill="${tint(c.body, 0.12)}"/>${mirror(`<ellipse cx="45" cy="72" rx="9" ry="8" fill="${tint(c.body, 0.12)}"/>`)}
      ${patch(c, 73, 20, 14)}
      ${face(c, { er: 4.7, iris: COPPER })}
    </g>`;
  },

  // ── Norwegian Forest Cat — long fur, TRIANGULAR face, big white bib, tufted ears, bushy tail ──
  norwegianforestcat: (c) => {
    const o = { flare: 2, eLx: 32, eLy: 18, eRx: 88, eRy: 18, biL: 53, biR: 67, chL: 43, chY: 50, dip: 40 };
    return `
    ${floorShadow(60, 111, 32)}
    ${tailBushy(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.15))}
      <path d="M35 60 q-6 10 1 20 q4 -9 7 -15 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>${mirror(`<path d="M35 60 q-6 10 1 20 q4 -9 7 -15 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <path d="M42 82 Q46 92 42 100 Q50 95 52 104 Q56 96 58 106 Q60 96 62 106 Q64 96 68 104 Q70 95 78 100 Q74 92 78 82 Q60 100 42 82 Z" fill="${belly(c)}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${patch(c, 73, 18, 13)}
      ${foreM(c, 55)}
      ${face(c, {})}
    </g>`;
  },

  // ── Munchkin — normal cat on comically SHORT stubby legs ──
  munchkin: (c) => {
    const legs = [41, 52, 66, 77].map((x) => `<rect x="${x}" y="94" width="7" height="14" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("");
    const body = `<path d="M60 100 C36 100 32 86 34 68 C35 60 38 54 43 50 L35 26 L54 44 Q60 40 66 44 L85 26 L77 50 C82 54 85 60 86 68 C88 86 84 100 60 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 111, 30)}
    <g class="tail-wag"><path d="M82 90 Q104 86 99 68 Q97 58 87 61 Q95 66 89 78 Q84 85 76 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${legs}
      ${body}
      ${inEar(35, 26, 43, 50, 54, 44, c.shade)}${mirror(inEar(35, 26, 43, 50, 54, 44, c.shade))}
      <path d="M46 86 Q60 96 74 86 Q72 96 60 97 Q48 96 46 86 Z" fill="${belly(c)}"/>
      ${patch(c, 74, 18, 13)}
      ${eyesOf(51, 69, 67, 4.2, INK)}${muzz(c, 60, 76)}${whisk(c)}
    </g>`;
  },

  // ── Savannah Cat — TALL & lanky (standing), enormous ears, bold dark SPOTS, gold eyes ──
  savannahcat: (c) => {
    const legs = [44, 53, 67, 76].map((x) => `<rect x="${x}" y="80" width="6" height="30" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("");
    const legSpots = [[47, 92], [47, 100], [70, 92], [70, 100]].map(([x, y]) => spot(c, x, y, 1.8)).join("");
    const body = `<path d="M60 86 C44 86 40 74 41 62 C42 54 45 49 49 46 L38 15 L55 41 Q60 37 65 41 L82 15 L71 46 C75 49 78 54 79 62 C80 74 76 86 60 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 112, 25)}
    <g class="tail-wag"><path d="M78 88 Q102 86 104 58 Q105 44 94 48 Q100 58 96 76 Q90 88 74 85 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><g stroke="${c.shade}" stroke-width="2.6" stroke-linecap="round" opacity=".85"><path d="M99 54 h5 M96 64 h5 M92 73 h5"/></g></g>
    <g class="breathe">
      ${legs}
      ${legSpots}
      ${body}
      ${inEar(38, 15, 49, 46, 55, 41, c.shade)}${mirror(inEar(38, 15, 49, 46, 55, 41, c.shade))}
      ${[[46, 62], [55, 66], [65, 66], [74, 62], [50, 74], [60, 76], [70, 74], [55, 82], [65, 82]].map(([x, y]) => spot(c, x, y, 3)).join("")}
      <ellipse cx="60" cy="58" rx="14" ry="10" fill="${belly(c)}"/>
      <path d="M52 50 q4 4 8 0 M60 46 v6" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".7"/>
      ${eyesOf(53, 67, 58, 4, GOLD)}${muzz(c, 60, 66)}${whisk(c)}
    </g>`;
  },

  // ── Burmese — sleek, compact & rounded, glossy solid coat, sweet golden eyes ──
  burmese: (c) => {
    const o = { flare: -1, eLx: 37, eLy: 23, eRx: 83, eRy: 23, chL: 43, chY: 50 };
    return `
    ${floorShadow(60, 111, 27)}
    ${tailCurl(c, c.body)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      <ellipse cx="60" cy="55" rx="16" ry="8" fill="${tint(c.body, 0.2)}" opacity=".55"/>
      <path d="M55 60 q5 4 10 0" fill="none" stroke="${c.shade}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
      ${patch(c, 74, 17, 12)}
      ${face(c, { er: 4.5, iris: GOLD })}
    </g>`;
  },

  // ── Birman — fluffy colourpoint like Ragdoll but signature WHITE GLOVED paws, blue eyes ──
  birman: (c) => {
    const o = { flare: 1, eLx: 33, eLy: 20, eRx: 87, eRy: 20, chL: 41 };
    const glove = `<ellipse cx="49" cy="107" rx="7.5" ry="5" fill="${WHITE}" stroke="${c.line}" stroke-width="1.8"/>`;
    return `
    ${floorShadow(60, 111, 30)}
    ${tailPoint(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.25))}
      <path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".8"/>${mirror(`<path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".8"/>`)}
      ${bib(c)}
      ${glove}${mirror(glove)}
      ${patch(c, 72, 19, 14)}
      <path d="M60 60 Q47 65 49 79 Q60 89 71 79 Q73 65 60 60 Z" fill="${c.shade}" opacity=".78"/>
      <ellipse cx="60" cy="74" rx="9" ry="7" fill="${belly(c)}" opacity=".9"/>
      ${face(c, { iris: BLUE })}
    </g>`;
  },

  // ── Manx — round rabbity body, TAILLESS (no tail at all), longer hop-legs, short ears ──
  manx: (c) => {
    const o = { flare: 3, eLx: 40, eLy: 24, eRx: 80, eRy: 24, biL: 52, biR: 68, biY: 43, dip: 42, chL: 42, chY: 50 };
    const hop = `<ellipse cx="43" cy="107" rx="8" ry="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`;
    return `
    ${floorShadow(60, 111, 31)}
    <g class="breathe">
      ${sit(c, o)}
      ${hop}${mirror(hop)}
      ${earsIn(o, c.shade)}
      <path d="M40 88 q20 8 40 0" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".35"/>
      ${patch(c, 73, 19, 14)}
      ${face(c, { er: 4.4 })}
    </g>`;
  },

  // ── Turkish Angora — slender & silky, light ear tufts, big PLUMED tail, refined ──
  turkishangora: (c) => {
    const o = { flare: -2, eLx: 33, eLy: 19, eRx: 87, eRy: 19, chL: 42, dip: 40 };
    return `
    ${floorShadow(60, 111, 27)}
    ${tailPlume(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.12))}
      <path d="M46 84 Q49 94 47 104 M54 86 v20 M60 86 v20 M66 86 v20 M73 86 Q71 94 73 104" fill="none" stroke="${tint(c.body, 0.3)}" stroke-width="1.5" stroke-linecap="round" opacity=".6"/>
      ${patch(c, 73, 18, 13)}
      ${face(c, {})}
    </g>`;
  },

  // ── Cornish Rex — slim arched body, big high-set ears, egg head, CURLY marcel-wave coat ──
  cornishrex: (c) => {
    const o = { flare: -3, eLx: 31, eLy: 16, eRx: 89, eRy: 16, biL: 52, biR: 68, chL: 41, chY: 47, dip: 39 };
    return `
    ${floorShadow(60, 111, 26)}
    ${tailThin(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      ${waves(c, [82, 90, 98])}
      <path d="M46 60 q4 -3 8 0 M66 60 q4 -3 8 0" fill="none" stroke="${c.shade}" stroke-width="1.4" stroke-linecap="round" opacity=".55"/>
      ${patch(c, 73, 17, 12)}
      ${face(c, {})}
    </g>`;
  },

  // ── Ocicat — wild look, rows of solid THUMBPRINT spots, tabby scarab forehead, amber eyes ──
  ocicat: (c) => {
    const o = { flare: 0, eLx: 34, eLy: 22, eRx: 86, eRy: 22, chL: 42 };
    return `
    ${floorShadow(60, 111, 28)}
    <g class="tail-wag"><path d="M80 98 Q104 94 99 74 Q97 63 86 66 Q95 72 88 84 Q82 92 74 91 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><g stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".8"><path d="M97 72 h6 M93 82 h6"/></g></g>
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      ${patch(c, 73, 18, 13)}
      ${foreM(c, 55)}
      ${[[43, 88], [53, 92], [63, 92], [73, 88], [48, 102], [60, 104], [72, 102], [38, 76], [82, 76]].map(([x, y]) => spot(c, x, y, 3.2)).join("")}
      ${face(c, { iris: AMBER })}
    </g>`;
  },

  // ── Chartreux — robust round build, full cheeks, the famous SMILE, copper-orange eyes ──
  chartreux: (c) => {
    const o = { flare: 4, eLx: 39, eLy: 25, eRx: 81, eRy: 25, biL: 53, biR: 67, biY: 44, dip: 44, chL: 43, chY: 51 };
    return `
    ${floorShadow(60, 111, 33)}
    ${tailCurl(c, c.body)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      <ellipse cx="46" cy="73" rx="8.5" ry="8" fill="${tint(c.body, 0.1)}"/>${mirror(`<ellipse cx="46" cy="73" rx="8.5" ry="8" fill="${tint(c.body, 0.1)}"/>`)}
      ${patch(c, 74, 19, 13)}
      ${face(c, { er: 4.4, iris: COPPER, smile: true, mzY: 74 })}
    </g>`;
  },

  // ── Devon Rex — pixie elf face, HUGE low-set bat ears, big eyes, curly coat ──
  devonrex: (c) => {
    const o = { flare: -2, eLx: 24, eLy: 27, eRx: 96, eRy: 27, biL: 50, biR: 70, biY: 44, chL: 42, chY: 46, dip: 40 };
    return `
    ${floorShadow(60, 111, 26)}
    ${tailThin(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, c.shade)}
      ${waves(c, [84, 92])}
      ${patch(c, 72, 17, 12)}
      ${face(c, { eL: 50, eR: 70, eY: 64, er: 4.9 })}
    </g>`;
  },

  // ── Snowshoe Cat — short-hair colourpoint, WHITE inverted-V blaze + white paws, blue eyes ──
  snowshoecat: (c) => {
    const o = { flare: 0, eLx: 34, eLy: 22, eRx: 86, eRy: 22, chL: 42 };
    const mitt = `<ellipse cx="49" cy="107" rx="7.5" ry="5" fill="${WHITE}" stroke="${c.line}" stroke-width="1.8"/>`;
    return `
    ${floorShadow(60, 111, 28)}
    ${tailPoint(c)}
    <g class="breathe">
      ${sit(c, o)}
      ${earsIn(o, deepen(c.body, 0.25))}
      <path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".8"/>${mirror(`<path d="M34 24 L41 49 L54 43 Q47 34 34 24 Z" fill="${c.shade}" opacity=".8"/>`)}
      ${mitt}${mirror(mitt)}
      ${patch(c, 72, 19, 14)}
      <path d="M60 60 Q48 64 50 78 Q60 88 70 78 Q72 64 60 60 Z" fill="${c.shade}" opacity=".78"/>
      <path d="M54 60 Q60 62 66 60 L61 80 Q60 82 59 80 Z" fill="${WHITE}"/>
      ${eyesOf(51, 69, 66, 4.2, BLUE)}${muzz(c, 60, 78)}${whisk(c)}
    </g>`;
  },
};

export const ROSTER_CATBREEDS = [
  { n: "Maine Coon",            e: "🐈", tier: 2, float: false },
  { n: "Bengal",                e: "🐆", tier: 2, float: false },
  { n: "Sphynx",                e: "🐈", tier: 2, float: false },
  { n: "Ragdoll",               e: "🐱", tier: 2, float: false },
  { n: "Russian Blue",          e: "🐈", tier: 2, float: false },
  { n: "Scottish Fold",         e: "🐱", tier: 1, float: false },
  { n: "Abyssinian",            e: "🐈", tier: 2, float: false },
  { n: "British Shorthair",     e: "🐱", tier: 1, float: false },
  { n: "Norwegian Forest Cat",  e: "🐈", tier: 2, float: false },
  { n: "Munchkin",              e: "🐱", tier: 1, float: false },
  { n: "Savannah Cat",          e: "🐆", tier: 2, float: false },
  { n: "Burmese",               e: "🐈", tier: 1, float: false },
  { n: "Birman",                e: "🐱", tier: 2, float: false },
  { n: "Manx",                  e: "🐈", tier: 1, float: false },
  { n: "Turkish Angora",        e: "🐱", tier: 2, float: false },
  { n: "Cornish Rex",           e: "🐈", tier: 1, float: false },
  { n: "Ocicat",                e: "🐆", tier: 2, float: false },
  { n: "Chartreux",             e: "🐱", tier: 1, float: false },
  { n: "Devon Rex",             e: "🐈", tier: 1, float: false },
  { n: "Snowshoe Cat",          e: "🐱", tier: 1, float: false },
];
