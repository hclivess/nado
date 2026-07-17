// farm.js — BESPOKE hand-drawn SVG art for DOMESTIC & FARM animals (NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120>, animal centered ~(60,62), within x,y ∈ [8,112].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/spots), c.line (outline stroke).
// Fixed warm accents are allowed for beaks/horns/combs (see BEAK/HORN/RED/TONGUE below); nose = INK.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const BEAK = "#f2a03b";   // beaks, bills, chicken/turkey feet
const HORN = "#f2c94c";   // horns, hooves
const RED = "#e0564d";    // combs, wattles, snood
const TONGUE = "#eb8f8f"; // dog tongues, cat noses

export const ART_FARM = {
  // ── DOGS ────────────────────────────────────────────────────────────────
  // Beagle — domed head, long low floppy hound ears, blunt muzzle, sits square
  beagle: (c) => `
    <g class="tail-wag"><path d="M84 82 Q100 76 102 60 Q94 66 88 74 Q90 66 84 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 92 q18 12 36 0" fill="${c.shade}" opacity=".55"/></g>
    <rect x="48" y="96" width="9" height="15" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <rect x="63" y="96" width="9" height="15" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="head-tilt">
      <path d="M42 46 Q26 54 31 78 Q42 78 47 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M42 46 Q26 54 31 78 Q42 78 47 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="50" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="61" rx="13" ry="9.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="56" rx="3.2" ry="2.6" fill="${INK}"/>
      <path d="M60 58 v4" stroke="${INK}" stroke-width="1.4"/>
      ${smile(60, 62, 4, INK)}
      ${eyes(52, 68, 47, 3, eyeInk(c))}
    </g>`,

  // Corgi — huge upright ears, long low body on tiny stub legs, white blaze & bib
  corgi: (c) => `
    <g class="tail-wag"><path d="M86 80 Q98 74 96 62 Q90 68 86 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="60" cy="82" rx="30" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 82 Q60 96 74 82 Q74 92 60 94 Q46 92 46 82 Z" fill="${c.shade}"/></g>
    ${[41, 54, 66, 79].map((x) => `<rect x="${x}" y="92" width="7" height="13" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      <path d="M44 40 L37 14 L59 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 37 L42 22 L54 34 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M44 40 L37 14 L59 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M46 37 L42 22 L54 34 Z" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="52" rx="21" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 46 Q60 42 68 46 L66 62 Q60 66 54 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="60" rx="9" ry="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="60" cy="57" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M55 64 q5 5 10 0 z" fill="${TONGUE}" stroke="${c.line}" stroke-width="1"/>
      ${eyes(52, 68, 50, 3, eyeInk(c))}
    </g>`,

  // Golden Retriever — soft rounded head, long feathered ears, fluffy chest, big open grin + tongue
  goldenretriever: (c) => `
    <g class="tail-wag">${tube("M30 82 Q14 74 15 54", c.body, c.line, 8)}</g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="27" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${pom(60, 78, 12, c.shade, c.line, 9, 1.6)}</g>
    <rect x="47" y="97" width="10" height="14" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <rect x="63" y="97" width="10" height="14" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="head-tilt">
      <path d="M42 44 Q28 56 34 80 Q46 78 49 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M42 44 Q28 56 34 80 Q46 78 49 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="50" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="60" rx="12" ry="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="55" rx="3.2" ry="2.6" fill="${INK}"/>
      <path d="M50 60 Q60 74 70 60 Q70 66 60 68 Q50 66 50 60 Z" fill="#3a2b28" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M56 65 q4 8 8 0 z" fill="${TONGUE}" stroke="${c.line}" stroke-width="1"/>
      ${eyes(52, 68, 47, 3, eyeInk(c))}
    </g>`,

  // Poodle — pompoms everywhere: top-knot, ear puffs, ankle cuffs, tail bobble
  poodle: (c) => `
    <g class="tail-wag">${tube("M42 82 Q26 76 22 62", c.body, c.line, 6)}${pom(21, 59, 8.5, c.body, c.line, 8, 1.8)}</g>
    ${tube("M46 90 L44 104", c.body, c.line, 5)}${tube("M74 90 L76 104", c.body, c.line, 5)}
    ${pom(44, 106, 6, c.body, c.line, 7, 1.8)}${pom(76, 106, 6, c.body, c.line, 7, 1.8)}
    <g class="breathe"><ellipse cx="60" cy="82" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${pom(60, 84, 13, c.body, c.line, 9, 1.4)}</g>
    <g class="head-tilt">
      ${pom(43, 46, 10, c.body, c.line, 8, 2)}${pom(77, 46, 10, c.body, c.line, 8, 2)}
      ${pom(60, 34, 13, c.body, c.line, 9, 2)}
      <ellipse cx="60" cy="54" rx="15" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="62" rx="9" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="60" cy="58" rx="2.8" ry="2.2" fill="${INK}"/>
      ${smile(60, 63, 3.4, INK)}
      ${eyes(53, 67, 51, 2.8, eyeInk(c))}
    </g>`,

  // Dachshund — the sausage: long low tube body, stubby legs, long tapered snout, one floppy ear
  dachshund: (c) => `
    <g class="tail-wag">${tube("M26 74 Q13 68 11 55", c.body, c.line, 5)}</g>
    ${[30, 44, 71, 85].map((x) => `<rect x="${x}" y="86" width="7" height="15" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="breathe"><rect x="24" y="64" width="64" height="26" rx="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M28 82 q30 8 58 0" fill="${c.shade}" opacity=".4"/></g>
    <g class="head-tilt">
      <path d="M82 58 Q100 55 107 68 Q109 79 98 82 Q85 82 80 73 Q78 64 82 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 55 Q77 62 80 80 Q90 77 92 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="106" cy="71" rx="2.6" ry="2.2" fill="${INK}"/>
      ${smile(102, 76, 3, INK)}
      ${eye(95, 64, 2.6, eyeInk(c))}
    </g>`,

  // ── CATS ────────────────────────────────────────────────────────────────
  // Siamese — slim, tall pointed ears with dark tips, dark mask/points, ice-almond eyes
  siamesecat: (c) => `
    <g class="tail-wag">${tube("M35 90 Q19 86 17 66", c.shade, c.line, 6)}</g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="19" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 98 h16" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="head-tilt">
      <path d="M47 44 L41 18 L59 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 40 L44 24 L55 37 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M47 44 L41 18 L59 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 40 L44 24 L55 37 Z" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="52" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 46 Q48 52 50 66 Q60 72 70 66 Q72 52 60 46 Z" fill="${c.shade}" opacity=".85"/>
      <path d="M60 60 l0 4" stroke="${INK}" stroke-width="1.4"/>
      <path d="M60 60 q-2 3 -2 3 M60 60 q2 3 2 3" fill="none" stroke="${INK}" stroke-width="1.3" stroke-linecap="round"/>
      <path d="M44 56 h-9 M44 60 h-9 M76 56 h9 M76 60 h9" stroke="${c.line}" stroke-width="1" opacity=".7"/>
      ${eyes(52, 68, 51, 3.2, "#4a7fb0")}
    </g>`,

  // Tabby — round face, striped forehead-M, cheek & body stripes, pink nose, whiskers
  tabbycat: (c) => `
    <g class="tail-wag">${tube("M36 90 Q22 88 21 72", c.body, c.line, 6)}
      <path d="M28 82 h10 M26 88 h10" stroke="${c.shade}" stroke-width="2.4"/></g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="21" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 80 h28 M46 87 h28 M48 94 h24" stroke="${c.shade}" stroke-width="2.6" stroke-linecap="round"/></g>
    <g class="head-tilt">
      <path d="M46 46 L42 26 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M47 42 L45 30 L54 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 46 L42 26 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 42 L45 30 L54 40 Z" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="54" rx="18" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 42 q3 7 6 3 q3 4 6 -3" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M46 52 h8 M46 57 h8 M66 52 h8 M66 57 h8" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>
      <path d="M60 60 l0 3" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="59" rx="2.4" ry="1.8" fill="${TONGUE}" stroke="${INK}" stroke-width=".8"/>
      <path d="M56 63 q4 4 8 0" fill="none" stroke="${INK}" stroke-width="1.2"/>
      <path d="M50 60 h-11 M50 63 h-11 M70 60 h11 M70 63 h11" stroke="${c.line}" stroke-width="1" opacity=".65"/>
      ${eyes(52, 68, 53, 3, eyeInk(c))}
    </g>`,

  // Persian — luxuriously fluffy round ball, tiny ears, flat squashed face, wide round eyes
  persiancat: (c) => `
    <g class="breathe">${pom(60, 84, 23, c.body, c.line, 13, 2.2)}
      ${pom(60, 88, 12, c.shade, c.line, 9, 1.2)}</g>
    <g class="head-tilt">
      <path d="M46 40 L44 28 L56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M46 40 L44 28 L56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      ${pom(60, 50, 19, c.body, c.line, 12, 2.4)}
      <ellipse cx="60" cy="55" rx="12" ry="9" fill="${c.shade}" opacity=".45"/>
      <path d="M60 54 l0 4 M60 58 q-3 3 -6 2 M60 58 q3 3 6 2" fill="none" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="53" rx="2.2" ry="1.6" fill="${TONGUE}"/>
      ${eyes(51, 69, 49, 3.4, "#c98a2e")}
    </g>`,

  // ── SMALL FURRIES ─────────────────────────────────────────────────────────
  // Rabbit — tall upright ears (pink inner), round body, cotton tail, buck teeth
  rabbit: (c) => `
    ${pom(33, 82, 8, c.shade, c.line, 8, 2)}
    <g class="breathe"><ellipse cx="60" cy="84" rx="22" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="90" rx="12" ry="8" fill="${c.shade}" opacity=".5"/></g>
    <ellipse cx="50" cy="100" rx="8" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <ellipse cx="70" cy="100" rx="8" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="tail-wag">
      <path d="M53 48 Q47 18 53 9 Q60 15 58 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M54 44 Q51 24 55 15 Q58 24 57 44 Z" fill="${TONGUE}" opacity=".6"/>
      ${mirror(`<path d="M53 48 Q47 18 53 9 Q60 15 58 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M54 44 Q51 24 55 15 Q58 24 57 44 Z" fill="${TONGUE}" opacity=".6"/>`)}
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="54" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 58 l0 3" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="57" rx="2.4" ry="1.8" fill="${TONGUE}" stroke="${INK}" stroke-width=".8"/>
      <rect x="57" y="61" width="6" height="6" rx="1" fill="#fff" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M60 61 v6" stroke="${c.line}" stroke-width="1"/>
      <path d="M52 58 h-10 M52 61 h-10 M68 58 h10 M68 61 h10" stroke="${c.line}" stroke-width=".9" opacity=".6"/>
      ${eyes(52, 68, 51, 3, eyeInk(c))}
    </g>`,

  // Guinea Pig — chunky tailless loaf, snub nose, small petal ears, a rosette swirl
  guineapig: (c) => `
    <g class="breathe"><ellipse cx="60" cy="76" rx="31" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 62 q10 4 6 16 q-4 6 -12 3" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="42" cy="84" rx="10" ry="8" fill="${c.shade}" opacity=".5"/></g>
    ${[46, 68].map((x) => `<ellipse cx="${x}" cy="95" rx="5" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}
    <g class="head-tilt">
      <path d="M40 58 Q34 56 34 64 Q40 66 44 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M52 56 Q46 52 44 58 Q49 62 54 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M40 68 l0 4 M40 72 q-3 2 -5 1 M40 72 q3 2 5 1" fill="none" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="40" cy="67" rx="2.2" ry="1.6" fill="${TONGUE}"/>
      ${eyes(38, 52, 62, 2.8, eyeInk(c))}
    </g>`,

  // Hamster — tiny round body, puffed cheek pouches, little paws held at chest, pale belly
  hamster: (c) => `
    <g class="breathe"><ellipse cx="60" cy="76" rx="25" ry="23" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="84" rx="15" ry="12" fill="${c.shade}" opacity=".55"/></g>
    <ellipse cx="53" cy="88" rx="5" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <ellipse cx="67" cy="88" rx="5" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <g class="head-tilt">
      <circle cx="47" cy="46" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="73" cy="46" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="41" cy="66" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="79" cy="66" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="60" cy="58" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 62 l0 3" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="61" rx="2.4" ry="1.8" fill="${INK}"/>
      ${smile(60, 65, 2.8, INK)}
      ${eyes(52, 68, 55, 3, eyeInk(c))}
    </g>`,

  // ── EQUINES ─────────────────────────────────────────────────────────────
  // Horse — proud profile: long neck, flowing mane, tapered muzzle, four tube legs, swishing tail
  horse: (c) => `
    <g class="tail-wag"><path d="M30 66 Q15 70 12 96 Q21 92 25 82 Q29 90 34 84 Q33 74 40 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${tube("M42 82 L40 104", c.body, c.line, 6)}${tube("M70 82 L72 104", c.body, c.line, 6)}
    <g class="breathe"><ellipse cx="52" cy="72" rx="27" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    ${tube("M46 80 L44 104", c.body, c.line, 6)}${tube("M64 80 L66 104", c.body, c.line, 6)}
    ${[40, 44, 64, 68].map((x) => `<rect x="${x}" y="102" width="7" height="7" rx="1.5" fill="${HORN}" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
    <g class="head-tilt">
      ${tube("M68 66 Q80 54 84 40", c.body, c.line, 13)}
      <path d="M80 30 Q98 28 99 48 Q99 60 88 62 Q78 60 76 46 Q76 34 80 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 30 Q68 42 72 66 Q66 60 66 68 Q60 48 72 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M82 30 L82 17 L91 28 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="93" cy="54" rx="6" ry="7" fill="${c.shade}" opacity=".5"/>
      <ellipse cx="95" cy="54" rx="1.8" ry="2.4" fill="${INK}"/>
      ${eye(86, 44, 2.8, eyeInk(c))}
    </g>`,

  // Pony — stocky short-legged cousin: round barrel, shaggy forelock & thick mane, tier-1 charmer
  pony: (c) => `
    <g class="tail-wag"><path d="M28 68 Q14 74 14 98 Q22 92 26 84 Q30 92 35 86 Q33 76 40 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${tube("M44 84 L42 102", c.body, c.line, 7)}${tube("M70 84 L72 102", c.body, c.line, 7)}
    <g class="breathe"><ellipse cx="52" cy="76" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    ${tube("M48 82 L46 102", c.body, c.line, 7)}${tube("M66 82 L64 102", c.body, c.line, 7)}
    ${[42, 46, 62, 70].map((x) => `<rect x="${x}" y="100" width="7" height="7" rx="1.5" fill="${HORN}" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
    <g class="head-tilt">
      ${tube("M70 68 Q78 58 82 48", c.body, c.line, 15)}
      <path d="M76 40 Q94 40 94 56 Q94 66 84 68 Q74 66 73 54 Q73 44 76 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 40 Q66 52 70 70 Q64 64 64 70 Q60 52 68 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M76 42 Q82 32 88 40 Q84 40 82 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M78 40 L78 28 L86 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="89" cy="60" rx="5" ry="6" fill="${c.shade}" opacity=".5"/>
      <ellipse cx="91" cy="60" rx="1.6" ry="2.2" fill="${INK}"/>
      ${eye(83, 52, 2.8, eyeInk(c))}
    </g>`,

  // Donkey — front-on, unmistakable enormous ears, long muzzle with pale mealy nose, forelock tuft
  donkey: (c) => `
    <g class="breathe"><ellipse cx="60" cy="88" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    ${[47, 66].map((x) => `<rect x="${x}" y="96" width="8" height="15" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><rect x="${x}" y="107" width="8" height="5" rx="1.5" fill="${INK}"/>`).join("")}
    <g class="tail-wag">
      <path d="M49 44 Q40 18 47 7 Q55 12 55 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 40 Q45 22 49 13 Q53 22 53 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M49 44 Q40 18 47 7 Q55 12 55 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M50 40 Q45 22 49 13 Q53 22 53 40 Z" fill="${c.shade}"/>`)}
    </g>
    <g class="head-tilt">
      <path d="M60 42 Q45 44 45 60 Q45 74 60 76 Q75 74 75 60 Q75 44 60 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 40 q5 -6 10 0 q-2 6 -5 6 q-3 0 -5 -6 z" fill="${c.shade}"/>
      <ellipse cx="60" cy="68" rx="12" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="55" cy="68" rx="1.8" ry="2.4" fill="${INK}"/><ellipse cx="65" cy="68" rx="1.8" ry="2.4" fill="${INK}"/>
      ${eyes(53, 67, 55, 3, eyeInk(c))}
    </g>`,

  // ── FARMYARD ────────────────────────────────────────────────────────────
  // Cow — patchy spots, curved horns, big ears out, broad pink muzzle with nostrils
  cow: (c) => `
    <g class="tail-wag">${tube("M85 84 Q98 82 98 66", c.body, c.line, 4)}<circle cx="98" cy="64" r="4" fill="${c.shade}"/></g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="29" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="46" cy="82" rx="8" ry="6.5" fill="${c.shade}"/><ellipse cx="74" cy="90" rx="9" ry="6.5" fill="${c.shade}"/></g>
    ${[46, 58, 66, 78].map((x) => `<rect x="${x}" y="98" width="7" height="13" rx="1.5" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/><rect x="${x}" y="107" width="7" height="4" rx="1" fill="${INK}"/>`).join("")}
    <g class="head-tilt">
      <path d="M46 42 Q35 34 34 24 Q42 27 47 38 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M46 42 Q35 34 34 24 Q42 27 47 38 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <ellipse cx="39" cy="48" rx="9" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2" transform="rotate(-24 39 48)"/>
      ${mirror(`<ellipse cx="39" cy="48" rx="9" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2" transform="rotate(-24 39 48)"/>`)}
      <ellipse cx="60" cy="52" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="52" cy="45" rx="6" ry="5" fill="${c.shade}"/>
      <ellipse cx="60" cy="63" rx="13" ry="9.5" fill="${TONGUE}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="55" cy="63" rx="1.8" ry="2.6" fill="${INK}"/><ellipse cx="65" cy="63" rx="1.8" ry="2.6" fill="${INK}"/>
      ${eyes(52, 68, 50, 3, eyeInk(c))}
    </g>`,

  // Pig — round barrel, big flat disc snout with nostrils, forward-flopping ears, curly tail
  pig: (c) => `
    <g class="tail-wag"><path d="M32 80 q-9 -1 -8 -8 q1 -6 7 -5 q4 1 3 6" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M32 80 q-9 -1 -8 -8 q1 -6 7 -5 q4 1 3 6" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="60" cy="82" rx="28" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    ${[46, 58, 66, 78].map((x) => `<rect x="${x}" y="94" width="8" height="14" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      <path d="M43 46 Q40 34 49 34 Q54 40 52 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M43 46 Q40 34 49 34 Q54 40 52 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="56" rx="19" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="64" rx="11" ry="8.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="56" cy="64" rx="1.8" ry="2.8" fill="${INK}"/><ellipse cx="64" cy="64" rx="1.8" ry="2.8" fill="${INK}"/>
      ${eyes(52, 68, 52, 3, eyeInk(c))}
    </g>`,

  // Sheep — billowing woolly cloud body & top curl, dark narrow face, floppy ears, thin dark legs
  sheep: (c) => `
    ${[50, 62].map((x) => `<rect x="${x}" y="92" width="6" height="16" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="breathe">${pom(60, 78, 25, c.body, c.line, 13, 2.4)}</g>
    <g class="head-tilt">
      ${pom(60, 44, 10, c.body, c.line, 8, 2)}
      <path d="M45 52 Q35 52 34 62 Q42 66 49 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M45 52 Q35 52 34 62 Q42 66 49 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="56" rx="13" ry="15" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 60 l0 4" stroke="${eyeInk(c)}" stroke-width="1.4"/>
      ${smile(60, 64, 3, eyeInk(c))}
      ${eyes(54, 66, 54, 2.8, eyeInk(c))}
    </g>`,

  // Goat — swept-back horns, chin beard, rectangular slot pupils, wattle-ish alert face
  goat: (c) => `
    <g class="tail-wag"><path d="M84 78 l8 -5 l-2 8 z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="60" cy="82" rx="25" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    ${[47, 58, 64, 75].map((x) => `<rect x="${x}" y="94" width="6" height="14" rx="1.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      <path d="M52 38 Q48 22 40 18 Q46 30 50 42 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M52 38 Q48 22 40 18 Q46 30 50 42 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M46 50 Q34 50 33 60 Q42 62 49 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M46 50 Q34 50 33 60 Q42 62 49 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M50 46 Q50 68 60 72 Q70 68 70 46 Q60 42 50 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="6" ry="5" fill="${c.shade}"/>
      <path d="M60 68 l0 3" stroke="${INK}" stroke-width="1.4"/>
      <path d="M55 72 Q60 82 65 72 Q60 78 55 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <g class="blink"><rect x="49" y="53" width="5.4" height="3.4" rx="1.2" fill="${eyeInk(c)}"/><rect x="65.6" y="53" width="5.4" height="3.4" rx="1.2" fill="${eyeInk(c)}"/></g>
    </g>`,

  // ── POULTRY ─────────────────────────────────────────────────────────────
  // Chicken — plump body, tucked wing, red comb & wattle, orange beak & feet, perky tail
  chicken: (c) => `
    <g class="tail-wag"><path d="M52 60 Q28 54 17 39 Q26 51 35 59 Q27 64 31 73 Q42 77 54 73 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="63" cy="78" rx="23" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 68 Q74 66 79 84 Q66 90 56 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    ${[58, 70].map((x) => `<path d="M${x} 96 l0 10 M${x} 106 l-4 4 M${x} 106 l4 4 M${x} 106 l0 5" stroke="${BEAK}" stroke-width="2.2" stroke-linecap="round"/>`).join("")}
    <g class="head-tilt">
      <path d="M58 40 q4 -8 9 -4 q3 -6 8 -1 q3 -5 7 1 q-1 6 -6 6 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="68" cy="52" rx="13" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M80 52 l11 3 l-10 5 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M76 60 q2 8 -3 9 q-3 -5 0 -9 z" fill="${RED}" stroke="${c.line}" stroke-width="1.4"/>
      ${eye(71, 49, 2.8, eyeInk(c))}
    </g>`,

  // Duck — rounded body, flat broad bill, short neck, folded wing, webbed feet
  duck: (c) => `
    <g class="tail-wag"><path d="M32 66 Q20 62 22 52 Q30 58 40 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="56" cy="76" rx="25" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 68 Q70 66 74 82 Q60 88 50 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    ${[52, 64].map((x) => `<path d="M${x} 92 l0 8 l-6 4 l12 0 z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
    <g class="head-tilt">
      ${tube("M72 64 Q80 54 81 46", c.body, c.line, 12)}
      <ellipse cx="82" cy="42" rx="11" ry="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M90 40 Q104 38 104 45 Q104 52 90 49 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="99" cy="45" rx="1.4" ry="1.8" fill="${INK}"/>
      ${eye(84, 39, 2.6, eyeInk(c))}
    </g>`,

  // Goose — S-curved long neck stretched up, slim body, knobbed bill, tail flick
  goose: (c) => `
    <g class="tail-wag"><path d="M30 78 Q18 76 18 66 Q26 70 36 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="52" cy="80" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 74 Q64 72 68 86 Q56 92 46 84 Z" fill="${c.shade}" opacity=".7"/></g>
    ${[48, 60].map((x) => `<path d="M${x} 94 l0 10 l-5 3 l10 0 z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
    <g class="head-tilt">
      ${tube("M66 72 Q84 62 82 34", c.body, c.line, 11)}
      <ellipse cx="83" cy="30" rx="10" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M91 27 Q102 27 102 33 Q102 39 91 37 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="90" cy="26" rx="2.6" ry="2.2" fill="${INK}"/>
      ${eye(85, 28, 2.4, eyeInk(c))}
    </g>`,

  // Turkey — spread fan of tail feathers, plump body, bald head with red snood & wattle
  turkey: (c) => `
    <g class="tail-wag">
      ${[-46, -30, -15, 0, 15, 30, 46].map((a, i) => `<g transform="rotate(${a} 60 84)"><ellipse cx="60" cy="40" rx="7.5" ry="20" fill="${i % 2 ? c.shade : c.body}" stroke="${c.line}" stroke-width="2"/><ellipse cx="60" cy="46" rx="4" ry="11" fill="${i % 2 ? c.body : c.shade}" opacity=".7"/></g>`).join("")}
    </g>
    <g class="breathe"><ellipse cx="60" cy="82" rx="20" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 66 Q46 72 48 88 Q60 96 72 88 Q74 72 60 66 Z" fill="${c.shade}"/></g>
    ${[54, 66].map((x) => `<path d="M${x} 98 l0 8 l-4 4 M${x} 106 l4 4 M${x} 106 l0 5" stroke="${BEAK}" stroke-width="2.2" stroke-linecap="round" fill="none"/>`).join("")}
    <g class="head-tilt">
      <ellipse cx="60" cy="56" rx="11" ry="12" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 46 Q52 38 55 34 Q59 40 58 47 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M52 52 l-9 2 l8 5 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M53 58 q-3 8 -7 8 q-1 -6 3 -10 z" fill="${RED}" stroke="${c.line}" stroke-width="1.4"/>
      ${eye(57, 52, 2.6, eyeInk(c))}
    </g>`,
};

export const ROSTER_FARM = [
  { n: "Beagle", e: "🐶", tier: 1, float: false },
  { n: "Corgi", e: "🐕", tier: 2, float: false },
  { n: "Golden Retriever", e: "🦮", tier: 2, float: false },
  { n: "Poodle", e: "🐩", tier: 2, float: false },
  { n: "Dachshund", e: "🌭", tier: 1, float: false },
  { n: "Siamese Cat", e: "🐱", tier: 2, float: false },
  { n: "Tabby Cat", e: "🐈", tier: 1, float: false },
  { n: "Persian Cat", e: "😺", tier: 2, float: false },
  { n: "Rabbit", e: "🐰", tier: 1, float: false },
  { n: "Guinea Pig", e: "🐭", tier: 1, float: false },
  { n: "Hamster", e: "🐹", tier: 1, float: false },
  { n: "Horse", e: "🐎", tier: 2, float: false },
  { n: "Pony", e: "🐴", tier: 1, float: false },
  { n: "Donkey", e: "🫏", tier: 1, float: false },
  { n: "Cow", e: "🐄", tier: 1, float: false },
  { n: "Pig", e: "🐷", tier: 1, float: false },
  { n: "Sheep", e: "🐑", tier: 1, float: false },
  { n: "Goat", e: "🐐", tier: 1, float: false },
  { n: "Chicken", e: "🐔", tier: 1, float: false },
  { n: "Duck", e: "🦆", tier: 1, float: false },
  { n: "Goose", e: "🦢", tier: 1, float: false },
  { n: "Turkey", e: "🦃", tier: 1, float: false },
];
