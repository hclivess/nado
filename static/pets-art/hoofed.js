// pets-art/hoofed.js — BESPOKE hand-drawn SVG art for HOOFED GRAZERS & ANTELOPE (NADO Pets).
// Each entry: slug -> (c, v) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,62),
// within x,y ∈ [8,112]. Palette-driven: c.body (main fill) · c.shade (underside/patches/stripes) ·
// c.line (outline). Horns/hooves use fixed ivory/amber/dark tints (real hues NOT hardcoded); nose INK.
// Animate: torso <g class="breathe">, head/face <g class="head-tilt">, tails/ears <g class="tail-wag">.
// Signature per species: bison/yak = shaggy hump; kudu/eland/bongo = spiral horns; oryx/gemsbok = long
// straight spears; ibex/bighorn/mouflon = big backward/curled horns; gazelle/impala/springbok = ringed lyre;
// pronghorn = forked prong; saiga = bulbous nose; okapi = white-striped legs. Keys == ROSTER `n` slugified.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const IVORY  = "#f0e6d2";  // pale ivory horns
const HORN   = "#d9c9a3";  // shaded ivory horn
const HORNDK = "#463d34";  // dark keratin horn (bison / wildebeest / gnu)
const AMBER  = "#e6c583";  // translucent saiga horn
const HOOF   = "#2e2a25";  // cloven hoof tips

// two ringed leg-strokes above a hoof-rect pair (front + mirror) — shared grazer legs
const legs = (c, xl, xr, y, w, h, hoof) => ["", "s"].map((_, i) =>
  `<rect x="${i ? xr : xl}" y="${y}" width="${w}" height="${h}" rx="${(w / 2.6).toFixed(1)}" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>` +
  (hoof ? `<rect x="${i ? xr : xl}" y="${y + h - 3.5}" width="${w}" height="3.5" rx="1.4" fill="${HOOF}"/>` : "")).join("");

export const ART_HOOFED = {
  // ── Bison — colossal shaggy shoulder hump, bearded low profile head, short black up-curled horns ─
  bison: (c) => `
    <g class="tail-wag"><path d="M86 86 Q95 90 92 102" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M90 100 l1 6 l4 -4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="breathe">
      <ellipse cx="70" cy="86" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M32 82 Q28 54 50 52 Q68 54 64 84 Q48 92 34 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 62 q10 -4 20 0 M42 70 q9 -3 18 0" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      <path d="M54 90 q18 9 34 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 50, 74, 94, 10, 15, true)}</g>
    <g class="head-tilt">
      ${pom(40, 60, 13, c.body, c.line, 11, 2.4)}
      <path d="M28 58 Q26 44 40 42 Q54 42 54 58 Q54 74 40 76 Q28 74 28 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${pom(40, 46, 10, c.shade, c.line, 10, 1.8)}
      <path d="M32 46 Q20 44 20 34 Q28 36 35 44 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M48 46 Q60 44 60 34 Q52 36 45 44 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M33 66 Q40 74 47 66 Q46 72 40 74 Q34 72 33 66 Z" fill="${c.shade}"/>
      <ellipse cx="40" cy="67" rx="4.2" ry="2.6" fill="${INK}"/>
      ${pom(40, 80, 6.5, c.body, c.line, 8, 1.6)}
      ${eyes(34, 46, 55, 2.4, eyeInk(c))}
    </g>`,

  // ── Yak — long shaggy skirt of hair hanging to the hocks, humped shoulders, wide sweeping horns ─
  yak: (c) => `
    <g class="tail-wag">${tube("M88 82 Q98 84 96 104", c.body, c.line, 5)}${pom(96, 104, 5, c.shade, c.line, 8, 1.6)}</g>
    <g class="breathe">
      <path d="M30 74 Q28 52 52 52 Q78 54 84 74 Q86 88 58 90 Q30 88 30 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${Array.from({ length: 8 }).map((_, i) => `<path d="M${34 + i * 6} 84 q-1 12 ${i % 2 ? 1 : -1} 22" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`).join("")}
      <path d="M36 90 q22 8 42 0" fill="${c.shade}" opacity=".45"/>
      ${legs(c, 46, 68, 100, 8, 9, true)}</g>
    <g class="head-tilt">
      <path d="M40 42 Q26 32 14 40 Q22 44 32 46 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M40 42 Q54 32 66 40 Q58 44 48 46 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${pom(40, 54, 12, c.body, c.line, 10, 2.4)}
      <path d="M30 56 Q28 44 40 44 Q52 44 52 56 Q52 70 40 72 Q30 70 30 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${pom(40, 44, 8, c.shade, c.line, 9, 1.6)}
      <path d="M33 62 Q40 70 47 62 Q46 68 40 70 Q34 68 33 62 Z" fill="${c.shade}"/>
      <ellipse cx="40" cy="63" rx="4" ry="2.4" fill="${INK}"/>
      ${eyes(34, 46, 52, 2.4, eyeInk(c))}
    </g>`,

  // ── Wildebeest — cow-boss horns curving out then up, long face, chin beard, short neck mane ─────
  wildebeest: (c) => `
    <g class="tail-wag">${tube("M84 84 Q94 88 92 106", c.body, c.line, 4)}<path d="M92 104 q0 4 -2 6 q4 -1 4 -6" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 74 Q42 64 54 62 Q52 72 50 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M44 88 q20 9 38 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 48, 72, 94, 8, 16, true)}</g>
    <path d="M50 78 Q42 58 50 44" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M50 78 Q42 58 50 44" fill="none" stroke="${c.body}" stroke-width="8.5" stroke-linecap="round"/>
    <path d="M44 70 q3 -6 8 -10 M44 60 q2 -6 6 -10" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round" opacity=".55"/>
    <g class="head-tilt">
      <path d="M52 40 Q40 40 40 30 Q48 30 54 36 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${mirror(`<path d="M52 40 Q40 40 40 30 Q48 30 54 36 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <path d="M50 40 q10 -5 20 0" fill="none" stroke="${HORNDK}" stroke-width="4" stroke-linecap="round"/>
      <path d="M50 44 Q48 62 54 70 Q60 74 66 70 Q72 62 70 44 Q60 38 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 66 q5 5 10 0 Q60 72 55 66 Z" fill="${c.shade}"/>
      <path d="M56 60 h8" stroke="${INK}" stroke-width="1.3"/>
      <ellipse cx="60" cy="68" rx="3.4" ry="2.4" fill="${INK}"/>
      ${pom(60, 76, 5.5, c.body, c.line, 7, 1.5)}
      ${eyes(53, 67, 50, 2.5, eyeInk(c))}
    </g>`,

  // ── Gnu (black wildebeest) — forward-hooking horns, upright brush mane, white horse-tail ────────
  gnu: (c) => `
    <g class="tail-wag"><path d="M82 82 Q94 86 96 108" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M82 82 Q94 86 96 108" fill="none" stroke="#f4efe6" stroke-width="3" stroke-linecap="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 88 q20 9 38 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 46, 70, 94, 8, 16, true)}</g>
    <path d="M50 78 Q44 58 52 44" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M50 78 Q44 58 52 44" fill="none" stroke="${c.body}" stroke-width="8.5" stroke-linecap="round"/>
    <g class="tail-wag">${["#f4efe6", c.line].map((col, i) => `<path d="M46 66 q4 -8 8 -16 M48 72 q5 -8 9 -16 M50 78 q6 -8 10 -14" fill="none" stroke="${col}" stroke-width="${i ? 3.6 : 2}" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M52 42 Q42 46 44 36 Q46 28 54 34 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${mirror(`<path d="M52 42 Q42 46 44 36 Q46 28 54 34 Z" fill="${HORNDK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <path d="M50 42 q10 -4 20 0" fill="none" stroke="${HORNDK}" stroke-width="3.5" stroke-linecap="round"/>
      <path d="M51 44 Q49 60 55 68 Q60 72 65 68 Q71 60 69 44 Q60 38 51 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 64 q6 5 12 0 Q60 70 54 64 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3.4" ry="2.4" fill="${INK}"/>
      ${pom(60, 74, 5, c.shade, c.line, 7, 1.5)}
      ${eyes(53, 67, 50, 2.5, eyeInk(c))}
    </g>`,

  // ── Gazelle — dainty, ringed near-parallel lyre horns, dark flank stripe, white belly ──────────
  gazelle: (c) => `
    <g class="tail-wag"><path d="M82 82 Q90 84 90 94" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="90" cy="94" r="2.4" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="82" rx="23" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 84 q22 6 44 0 q-2 6 -22 7 q-20 -1 -22 -7 Z" fill="#f4efe6"/>
      <path d="M36 82 q22 4 44 0" fill="none" stroke="${INK}" stroke-width="5" opacity="1"/>
      ${legs(c, 46, 68, 92, 6, 18, true)}</g>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.body}" stroke-width="6.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M55 44 Q52 24 56 8" fill="none" stroke="${HORN}" stroke-width="3" stroke-linecap="round"/>
      ${mirror(`<path d="M55 44 Q52 24 56 8" fill="none" stroke="${HORN}" stroke-width="3" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M52 28 l4 0 M51 22 l4 0 M51 15 l4 0" stroke="${c.line}" stroke-width="1"/></g>`).join("")}
      <path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 46 Q54 60 60 64 M66 46 Q66 60 60 64" fill="none" stroke="#f4efe6" stroke-width="3" opacity=".8"/>
      <ellipse cx="60" cy="63" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 46, 2.6, eyeInk(c))}
    </g>`,

  // ── Impala — wide-spread ridged lyre horns (S-curve), slender russet build, black heel tufts ────
  impala: (c) => `
    <g class="tail-wag"><path d="M82 82 Q90 84 89 94" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><path d="M87 92 l2 4 l2 -4" fill="#f4efe6" stroke="${c.line}" stroke-width="1"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="82" rx="23" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 86 q22 6 44 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 46, 68, 92, 6, 18, true)}
      <path d="M46 108 q0 3 2 3 M70 108 q0 3 -2 3" stroke="${INK}" stroke-width="2.4"/></g>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.body}" stroke-width="6.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M55 44 Q43 28 46 11 Q48 3 56 8" fill="none" stroke="${HORN}" stroke-width="3.2" stroke-linecap="round"/>
      ${mirror(`<path d="M55 44 Q43 28 46 11 Q48 3 56 8" fill="none" stroke="${HORN}" stroke-width="3.2" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M52 28 l5 1 M49 22 l5 1 M48 16 l5 1" stroke="${c.line}" stroke-width="1"/></g>`).join("")}
      <path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 60 q6 5 12 0 Q60 66 54 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="63" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 46, 2.6, eyeInk(c))}
    </g>`,

  // ── Oryx — impossibly long, near-straight rapier horns swept back in a narrow V, small ears ─────
  oryx: (c) => `
    <g class="tail-wag"><path d="M84 82 Q94 86 93 104" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M91 102 q0 4 2 6 q3 -2 2 -6" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 78 q20 5 40 0" fill="none" stroke="${INK}" stroke-width="2" opacity=".5"/>
      <path d="M42 90 q18 8 36 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 48, 70, 94, 7, 16, true)}
      <path d="M48 92 v14 M72 92 v14" stroke="${INK}" stroke-width="1.6" opacity=".5"/></g>
    <g class="head-tilt">
      <path d="M55 34 Q49 18 40 4" fill="none" stroke="${IVORY}" stroke-width="3.4" stroke-linecap="round"/>
      ${mirror(`<path d="M55 34 Q49 18 40 4" fill="none" stroke="${IVORY}" stroke-width="3.4" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M53 28 l4 0 M51 21 l4 0 M49 14 l4 0 M46 8 l4 0" stroke="${c.line}" stroke-width="1"/></g>`).join("")}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 40 Q50 60 60 70 Q70 60 68 40 Q60 34 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 42 v18 M64 42 v18" stroke="${c.shade}" stroke-width="2.6" opacity=".7"/>
      <path d="M54 64 q6 4 12 0 Q60 70 54 64 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Kudu — grand corkscrew SPIRAL horns, huge round ears, thin white body stripes (tier 3) ──────
  kudu: (c) => `
    <g class="tail-wag"><path d="M84 84 Q94 88 92 106" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M90 104 q0 4 2 6 q3 -2 2 -6" fill="#f4efe6"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <g stroke="#f4efe6" stroke-width="2" opacity=".8"><path d="M46 72 q-1 10 0 20 M56 71 q-1 11 0 22 M66 72 q1 10 0 20 M75 74 q1 8 0 16"/></g>
      ${legs(c, 48, 70, 94, 7, 16, true)}</g>
    <path d="M50 80 Q45 58 52 44" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M50 80 Q45 58 52 44" fill="none" stroke="${c.body}" stroke-width="8.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M57 47 L53 36 Q66 30 56 20 Q46 14 58 6 Q52 4 50 8" fill="none" stroke="${HORN}" stroke-width="3.4" stroke-linecap="round"/>
      ${mirror(`<path d="M57 47 L53 36 Q66 30 56 20 Q46 14 58 6 Q52 4 50 8" fill="none" stroke="${HORN}" stroke-width="3.4" stroke-linecap="round"/>`)}
      <path d="M46 40 Q30 34 28 48 Q36 54 48 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 44 Q34 44 33 49" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".7"/>
      ${mirror(`<path d="M46 40 Q30 34 28 48 Q36 54 48 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M40 44 Q34 44 33 49" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".7"/>`)}
      <path d="M52 44 Q50 62 60 70 Q70 62 68 44 Q60 38 52 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 48 q6 -3 12 0" fill="none" stroke="#f4efe6" stroke-width="2" opacity=".85"/>
      <path d="M54 64 q6 4 12 0 Q60 70 54 64 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}
    </g>`,

  // ── Ibex — enormous scimitar horns sweeping back with knurled front ridges, goat beard ──────────
  ibex: (c) => `
    <g class="tail-wag"><path d="M82 82 Q90 84 89 94" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="89" cy="94" r="2.4" fill="${c.shade}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 88 q18 8 36 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 48, 70, 94, 8, 15, true)}</g>
    <g class="head-tilt">
      <path d="M56 47 L53 36 Q47 16 66 6" fill="none" stroke="${HORN}" stroke-width="4.4" stroke-linecap="round"/>
      ${mirror(`<path d="M56 47 L53 36 Q47 16 66 6" fill="none" stroke="${HORN}" stroke-width="4.4" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M51 30 h6 M50 24 h7 M51 18 h6 M54 12 h6" stroke="${c.line}" stroke-width="1.2"/></g>`).join("")}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 42 Q50 60 60 68 Q70 60 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 62 q6 4 12 0 Q60 68 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="64" rx="3" ry="2.2" fill="${INK}"/>
      ${pom(60, 74, 5.5, c.shade, c.line, 8, 1.5)}
      ${eyes(53, 67, 50, 2.6, eyeInk(c))}
    </g>`,

  // ── Bighorn Sheep — massive forward-curling ram horns (full curl), stocky woolly build ──────────
  bighornsheep: (c) => `
    <g class="tail-wag"><path d="M82 84 Q90 86 88 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="86" rx="25" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 90 q20 9 40 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 48, 70, 96, 9, 14, true)}</g>
    <g class="head-tilt">
      <path d="M50 42 Q32 42 32 26 Q32 12 48 15 Q60 18 55 32" fill="none" stroke="${HORN}" stroke-width="5.5" stroke-linecap="round"/>
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M44 40 q-6 -2 -10 -6 M40 30 q-6 0 -9 -4 M42 20 q-4 -3 -6 -8" stroke="${c.line}" stroke-width="1.2" opacity=".6"/></g>`).join("")}
      ${mirror(`<path d="M50 42 Q32 42 32 26 Q32 12 48 15 Q60 18 55 32" fill="none" stroke="${HORN}" stroke-width="5.5" stroke-linecap="round"/>`)}
      <path d="M52 42 Q50 60 60 68 Q70 60 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 46 q6 -3 12 0" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
      <path d="M54 62 q6 4 12 0 Q60 68 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="64" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 50, 2.6, eyeInk(c))}
    </g>`,

  // ── Reindeer — big beaded antlers with a forward brow shovel, furry ruff, cloven feet ───────────
  reindeer: (c) => `
    <g class="tail-wag"><path d="M84 84 Q92 86 91 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="91" cy="96" r="2.4" fill="#f4efe6"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 88 q18 8 36 0" fill="#f4efe6" opacity=".7"/>
      ${legs(c, 48, 70, 94, 8, 15, true)}</g>
    <g class="head-tilt">
      <g class="tail-wag">
        <path d="M52 40 Q46 16 36 8 M50 24 Q40 20 32 24 M50 32 Q42 36 38 44 M48 18 Q40 12 34 12" fill="none" stroke="${IVORY}" stroke-width="3" stroke-linecap="round"/>
        ${mirror(`<path d="M52 40 Q46 16 36 8 M50 24 Q40 20 32 24 M50 32 Q42 36 38 44 M48 18 Q40 12 34 12" fill="none" stroke="${IVORY}" stroke-width="3" stroke-linecap="round"/>`)}
      </g>
      ${pom(60, 52, 15, c.body, c.line, 12, 2.4)}
      <path d="M48 44 Q40 42 40 50 Q45 53 50 49 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 44 Q40 42 40 50 Q45 53 50 49 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 46 Q50 62 60 70 Q70 62 68 46 Q60 40 52 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 64 q5 5 10 0 Q60 70 55 64 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3.4" ry="2.6" fill="${INK}"/>
      ${eyes(53, 67, 52, 2.6, eyeInk(c))}
    </g>`,

  // ── Bongo — twisted lyre horns, bold vertical white body stripes on chestnut coat, big ears ─────
  bongo: (c) => `
    <g class="tail-wag"><path d="M84 84 Q93 88 91 104" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M89 102 q0 4 2 6 q3 -2 2 -6" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <g stroke="#f4efe6" stroke-width="2.6" opacity=".85" stroke-linecap="round"><path d="M44 71 q-1 12 0 22 M53 70 q-1 13 0 24 M62 70 q1 12 0 23 M71 72 q1 11 0 20"/></g>
      ${legs(c, 48, 70, 94, 7, 16, true)}</g>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.line}" stroke-width="11" stroke-linecap="round"/>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.body}" stroke-width="7.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M57 46 L54 34 Q64 26 56 14 Q52 8 58 4" fill="none" stroke="${HORN}" stroke-width="3.2" stroke-linecap="round"/>
      ${mirror(`<path d="M57 46 L54 34 Q64 26 56 14 Q52 8 58 4" fill="none" stroke="${HORN}" stroke-width="3.2" stroke-linecap="round"/>`)}
      <path d="M47 38 Q34 32 32 44 Q40 49 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M47 38 Q34 32 32 44 Q40 49 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <path d="M52 42 Q50 60 60 68 Q70 60 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 46 q6 -3 12 0" fill="none" stroke="#f4efe6" stroke-width="2.2" opacity=".9"/>
      <path d="M54 62 q6 4 12 0 Q60 68 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="64" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 50, 2.6, eyeInk(c))}
    </g>`,

  // ── Okapi — giraffe cousin: long neck, felt ossicones, white ZEBRA-STRIPED legs & rump (tier 3) ─
  okapi: (c) => `
    <g class="tail-wag"><path d="M82 82 Q92 84 92 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="92" cy="96" r="2.4" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <g stroke="#f4efe6" stroke-width="2.4" opacity=".9"><path d="M74 78 q6 2 8 8 M76 86 q5 1 8 6 M42 78 q-6 2 -8 8"/></g>
      ${["", "s"].map((_, i) => `<rect x="${i ? 68 : 46}" y="94" width="7" height="16" rx="2.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>` +
        `<g stroke="#f4efe6" stroke-width="2.2">${[97, 101, 105].map(y => `<path d="M${i ? 68 : 46} ${y} h7"/>`).join("")}</g>` +
        `<rect x="${i ? 68 : 46}" y="106.5" width="7" height="3.5" rx="1.4" fill="${HOOF}"/>`).join("")}</g>
    <path d="M50 80 Q42 54 52 38" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
    <path d="M50 80 Q42 54 52 38" fill="none" stroke="${c.body}" stroke-width="9" stroke-linecap="round"/>
    <g class="head-tilt">
      <line x1="53" y1="34" x2="50" y2="22" stroke="${c.line}" stroke-width="3"/><circle cx="49" cy="20" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<line x1="53" y1="34" x2="50" y2="22" stroke="${c.line}" stroke-width="3"/><circle cx="49" cy="20" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M50 32 Q42 30 42 38 Q47 41 52 37 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M50 32 Q42 30 42 38 Q47 41 52 37 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M50 34 Q66 34 68 46 Q70 56 58 58 Q48 56 48 42 Q48 36 50 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 52 Q68 54 66 46 Q60 48 58 52 Z" fill="${c.shade}"/>
      <path d="M52 38 q8 -2 14 2" fill="none" stroke="#f4efe6" stroke-width="2" opacity=".8"/>
      <ellipse cx="63" cy="51" rx="1.6" ry="1.2" fill="${INK}"/><ellipse cx="60" cy="53" rx="1.6" ry="1.2" fill="${INK}"/>
      ${eyes(53, 60, 42, 2.4, eyeInk(c))}
    </g>`,

  // ── Pronghorn — unique forked horns (forward prong + hooked tip), white throat bands ────────────
  pronghorn: (c) => `
    <g class="tail-wag"><path d="M82 84 Q90 86 89 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="89" cy="96" r="2.4" fill="#f4efe6"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="82" rx="23" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 84 q22 6 44 0 q-2 5 -22 6 q-20 -1 -22 -6 Z" fill="#f4efe6"/>
      ${legs(c, 46, 68, 92, 7, 17, true)}</g>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M50 80 Q46 60 52 46" fill="none" stroke="${c.body}" stroke-width="6.5" stroke-linecap="round"/>
    <path d="M52 66 q8 -3 14 -1 M53 72 q6 -2 12 0" fill="none" stroke="#f4efe6" stroke-width="2.6"/>
    <g class="head-tilt">
      <path d="M55 44 Q54 27 57 16" fill="none" stroke="${HORNDK}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M56 30 Q49 25 46 30" fill="none" stroke="${HORNDK}" stroke-width="2.8" stroke-linecap="round"/>
      ${mirror(`<path d="M55 44 Q54 27 57 16" fill="none" stroke="${HORNDK}" stroke-width="3.4" stroke-linecap="round"/><path d="M56 30 Q49 25 46 30" fill="none" stroke="${HORNDK}" stroke-width="2.8" stroke-linecap="round"/>`)}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 58 Q60 66 66 58 Q60 64 54 58 Z" fill="#f4efe6"/>
      <ellipse cx="60" cy="63" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Springbok — pronking gazelle, S-lyre horns, dark flank band, white face w/ eye stripe ───────
  springbok: (c) => `
    <g class="tail-wag"><path d="M84 78 Q92 80 91 90" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><path d="M89 88 l2 4 l2 -4" fill="${INK}" stroke="${c.line}" stroke-width="0.8"/></g>
    <g class="breathe">
      <path d="M36 82 Q40 62 60 60 Q80 62 84 82 Q84 90 60 90 Q36 90 36 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M38 82 q22 6 44 0 q-2 6 -22 7 q-20 -1 -22 -7 Z" fill="#f4efe6"/>
      <path d="M38 80 q22 4 44 0" fill="none" stroke="#a8543a" stroke-width="4.5" opacity=".9"/>
      ${legs(c, 46, 68, 90, 6, 19, true)}</g>
    <path d="M50 74 Q46 56 54 44" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M50 74 Q46 56 54 44" fill="none" stroke="${c.body}" stroke-width="6.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M55 43 Q47 30 46 18 Q47 10 53 13" fill="none" stroke="${HORNDK}" stroke-width="3" stroke-linecap="round"/>
      ${mirror(`<path d="M55 43 Q47 30 46 18 Q47 10 53 13" fill="none" stroke="${HORNDK}" stroke-width="3" stroke-linecap="round"/>`)}
      <path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M48 38 Q38 34 38 44 Q44 48 50 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M52 40 Q50 58 60 66 Q70 58 68 40 Q60 34 52 40 Z" fill="#f4efe6" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 42 Q52 56 58 62 M66 42 Q68 56 62 62" fill="none" stroke="${c.shade}" stroke-width="2.6"/>
      <path d="M54 62 q6 4 12 0 Q60 66 54 62 Z" fill="${INK}"/>
      ${eyes(53, 67, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Eland — biggest antelope: tightly spiralled straight horns, throat dewlap, shoulder hump ────
  eland: (c) => `
    <g class="tail-wag"><path d="M86 86 Q96 90 94 108" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M92 106 q0 4 2 6 q3 -2 2 -6" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="64" cy="86" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 80 Q40 66 54 64 Q52 74 50 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M48 90 q20 8 38 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 52, 74, 96, 9, 14, true)}</g>
    <path d="M52 80 Q44 60 52 46" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
    <path d="M52 80 Q44 60 52 46" fill="none" stroke="${c.body}" stroke-width="9" stroke-linecap="round"/>
    <path d="M50 66 Q42 78 50 88 Q56 80 54 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    <g class="head-tilt">
      <path d="M55 34 Q52 16 47 4" fill="none" stroke="${HORN}" stroke-width="3.6" stroke-linecap="round"/>
      ${mirror(`<path d="M55 34 Q52 16 47 4" fill="none" stroke="${HORN}" stroke-width="3.6" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M53 30 l4 -2 M52 24 l4 -2 M50 18 l4 -2 M49 12 l4 -2" stroke="${c.line}" stroke-width="1.2"/></g>`).join("")}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 42 Q50 60 60 68 Q70 60 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 62 q6 4 12 0 Q60 68 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="64" rx="3" ry="2.4" fill="${INK}"/>
      ${eyes(53, 67, 50, 2.6, eyeInk(c))}
    </g>`,

  // ── Gemsbok — oryx with the bold black-&-white harlequin face mask + long straight rapier horns ──
  gemsbok: (c) => `
    <g class="tail-wag"><path d="M84 84 Q94 88 93 106" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M91 104 q0 4 2 6 q3 -2 2 -6" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 82 q24 5 48 0" fill="none" stroke="${INK}" stroke-width="2.6" opacity=".6"/>
      <path d="M42 90 q18 7 36 0" fill="#f4efe6" opacity=".7"/>
      ${legs(c, 48, 70, 94, 7, 16, true)}
      <path d="M48 94 v6 M72 94 v6" stroke="${INK}" stroke-width="2" opacity=".55"/></g>
    <g class="head-tilt">
      <path d="M55 34 Q49 16 42 2" fill="none" stroke="${IVORY}" stroke-width="3.2" stroke-linecap="round"/>
      ${mirror(`<path d="M55 34 Q49 16 42 2" fill="none" stroke="${IVORY}" stroke-width="3.2" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M53 28 l4 0 M51 20 l4 0 M49 12 l4 0" stroke="${c.line}" stroke-width="1"/></g>`).join("")}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 40 Q50 60 60 70 Q70 60 68 40 Q60 34 52 40 Z" fill="#f4efe6" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 40 h4 l-2 12 Z" fill="${INK}"/>
      <path d="M52 44 Q49 56 53 64 M68 44 Q71 56 67 64" fill="none" stroke="${INK}" stroke-width="3.4"/>
      <path d="M54 64 q6 4 12 0 Q60 70 54 64 Z" fill="${INK}"/>
      ${eyes(53, 67, 48, 2.6, "#e9edf2")}
    </g>`,

  // ── Mouflon — wild sheep: single-curl horns, pale saddle patch on the back, sturdy woolly build ──
  mouflon: (c) => `
    <g class="tail-wag"><path d="M82 84 Q90 86 88 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="85" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 72 Q60 68 72 72 Q70 80 60 80 Q50 80 48 72 Z" fill="#f4efe6" opacity=".75"/>
      <path d="M42 90 q18 8 36 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 48, 70, 96, 8, 14, true)}</g>
    <g class="head-tilt">
      <path d="M50 40 Q36 42 36 30 Q36 20 48 22 Q57 25 53 34" fill="none" stroke="${HORN}" stroke-width="4.6" stroke-linecap="round"/>
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M46 38 q-6 -1 -9 -4 M43 30 q-5 -1 -7 -3" stroke="${c.line}" stroke-width="1.2" opacity=".6"/></g>`).join("")}
      ${mirror(`<path d="M50 40 Q36 42 36 30 Q36 20 48 22 Q57 25 53 34" fill="none" stroke="${HORN}" stroke-width="4.6" stroke-linecap="round"/>`)}
      <path d="M52 42 Q50 60 60 68 Q70 60 68 42 Q60 36 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 46 q6 -2 12 0" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
      <path d="M54 62 q6 4 12 0 Q60 68 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="64" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 50, 2.6, eyeInk(c))}
    </g>`,

  // ── Chamois — small goat-antelope: slim horns hooking sharply back at the tips, black eye-mask ───
  chamois: (c) => `
    <g class="tail-wag"><path d="M82 84 Q90 86 89 94" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="89" cy="94" r="2.2" fill="${INK}"/></g>
    <g class="breathe">
      <ellipse cx="59" cy="84" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 88 q18 7 36 0" fill="${c.shade}" opacity=".5"/>
      ${legs(c, 47, 68, 94, 6, 16, true)}</g>
    <path d="M50 80 Q47 62 53 48" fill="none" stroke="${c.line}" stroke-width="9" stroke-linecap="round"/>
    <path d="M50 80 Q47 62 53 48" fill="none" stroke="${c.body}" stroke-width="5.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M56 46 L55 34 L54 16 Q54 10 49 12" fill="none" stroke="${HORNDK}" stroke-width="2.8" stroke-linecap="round"/>
      ${mirror(`<path d="M56 46 L55 34 L54 16 Q54 10 49 12" fill="none" stroke="${HORNDK}" stroke-width="2.8" stroke-linecap="round"/>`)}
      <path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q40 38 40 46 Q45 49 50 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M52 42 Q50 58 60 66 Q70 58 68 42 Q60 36 52 42 Z" fill="#f4efe6" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M53 46 Q52 54 57 58 M67 46 Q68 54 63 58" fill="none" stroke="${INK}" stroke-width="3"/>
      <path d="M54 60 q6 4 12 0 Q60 66 54 60 Z" fill="${INK}"/>
      ${eyes(53, 67, 48, 2.5, INK)}
    </g>`,

  // ── Saiga — surreal bulbous over-hanging proboscis nose, amber ringed horns, pale steppe coat ────
  saiga: (c) => `
    <g class="tail-wag"><path d="M82 84 Q90 86 89 94" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="89" cy="94" r="2.2" fill="${c.shade}"/></g>
    <g class="breathe">
      <ellipse cx="59" cy="84" rx="23" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 88 q18 7 36 0" fill="#f4efe6" opacity=".7"/>
      ${legs(c, 47, 68, 94, 6, 16, true)}</g>
    <g class="head-tilt">
      <path d="M55 46 L53 36 Q52 18 55 6" fill="none" stroke="${AMBER}" stroke-width="3.4" stroke-linecap="round"/>
      ${mirror(`<path d="M55 46 L53 36 Q52 18 55 6" fill="none" stroke="${AMBER}" stroke-width="3.4" stroke-linecap="round"/>`)}
      ${["", "s"].map((_, i) => `<g${i ? ` transform="translate(120 0) scale(-1 1)"` : ""}><path d="M51 30 l4 0 M51 24 l4 0 M52 18 l4 0 M53 12 l4 0" stroke="${c.line}" stroke-width="1"/></g>`).join("")}
      <path d="M48 40 Q41 38 41 46 Q46 49 51 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<path d="M48 40 Q41 38 41 46 Q46 49 51 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <path d="M50 42 Q48 52 52 56 Q46 58 46 66 Q48 76 60 78 Q72 76 74 66 Q74 58 68 56 Q72 52 70 42 Q60 36 50 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 66 Q60 74 68 66 Q60 72 52 66 Z" fill="${c.shade}"/>
      <ellipse cx="55" cy="68" rx="2.4" ry="3" fill="${INK}"/><ellipse cx="65" cy="68" rx="2.4" ry="3" fill="${INK}"/>
      ${eyes(52, 68, 50, 2.6, eyeInk(c))}
    </g>`,
};

// roster metadata — every `n` slugifies to an ART_HOOFED key above
export const ROSTER_HOOFED = [
  { n: "Bison",          e: "🦬", tier: 2, float: false },
  { n: "Yak",            e: "🐂", tier: 2, float: false },
  { n: "Wildebeest",     e: "🐃", tier: 1, float: false },
  { n: "Gnu",            e: "🐃", tier: 1, float: false },
  { n: "Gazelle",        e: "🦌", tier: 1, float: false },
  { n: "Impala",         e: "🦌", tier: 1, float: false },
  { n: "Oryx",           e: "🦌", tier: 3, float: false },
  { n: "Kudu",           e: "🦌", tier: 3, float: false },
  { n: "Ibex",           e: "🐐", tier: 2, float: false },
  { n: "Bighorn Sheep",  e: "🐏", tier: 2, float: false },
  { n: "Reindeer",       e: "🦌", tier: 1, float: false },
  { n: "Bongo",          e: "🦌", tier: 3, float: false },
  { n: "Okapi",          e: "🦒", tier: 3, float: false },
  { n: "Pronghorn",      e: "🦌", tier: 1, float: false },
  { n: "Springbok",      e: "🦌", tier: 1, float: false },
  { n: "Eland",          e: "🐂", tier: 2, float: false },
  { n: "Gemsbok",        e: "🦌", tier: 2, float: false },
  { n: "Mouflon",        e: "🐏", tier: 2, float: false },
  { n: "Chamois",        e: "🐐", tier: 2, float: false },
  { n: "Saiga",          e: "🐐", tier: 3, float: false },
];
