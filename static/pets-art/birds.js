// birds.js — BESPOKE hand-drawn SVG art for BIRDS (NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,62), within x,y ∈ [8,112].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/belly/spots), c.line (outline stroke).
// Fixed warm accents allowed for beaks/legs/talons (BEAK/RAPTOR/LEG/… below); nose/eyes = INK/eyeInk.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const BEAK = "#f2a03b";   // orange beak / bill
const BEAKD = "#d97b2c";  // darker beak shading / hook underside
const RAPTOR = "#f2c94c"; // yellow raptor beak, cere & talons
const LEG = "#e79a3a";    // scaly legs / webbed feet
const OCE = "#f2c94c";    // peacock ocellus gold
const TIP = "#e0564d";    // red bill-tip / puffin outer band / crest flash
const YEL = "#f4c84a";    // puffin inner beak band / toucan beak yellow
const WHT = "#fbf6ee";    // eye-ring / cheek highlight (not coat — a highlight)

// twig songbird legs: perched/standing thin scaly legs with three splayed toes
const legs = (xs, y = 90, h = 12) => xs.map((x) =>
  `<path d="M${x} ${y} l0 ${h} M${x} ${y + h} l-4 4 M${x} ${y + h} l4 4 M${x} ${y + h} l0 5" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");
// heavy raptor talons: thick clenched yellow feet
const talons = (xs, y) => xs.map((x) =>
  `<path d="M${x} ${y} l0 7 M${x - 5} ${y + 7} h10 M${x - 4} ${y + 7} l-2 5 M${x + 4} ${y + 7} l2 5 M${x} ${y + 7} l0 5" stroke="${RAPTOR}" stroke-width="2.6" fill="none" stroke-linecap="round"/>`).join("");

export const ART_BIRDS = {
  // ── RAPTORS ───────────────────────────────────────────────────────────────
  // Bald Eagle — front-facing menace: pale hooded head, heavy hooked beak, fierce brow, broad shoulders, talons
  baldeagle: (c) => `
    <g class="tail-wag"><path d="M46 92 Q40 110 54 108 L60 98 L66 108 Q80 110 74 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M32 66 Q26 44 42 40 Q46 60 46 80 Q37 82 32 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M32 66 Q26 44 42 40 Q46 60 46 80 Q37 82 32 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M40 56 Q60 48 80 56 Q86 84 60 98 Q34 84 40 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 68 q6 5 0 9 M55 72 q6 5 0 9 M65 72 q-6 5 0 9 M72 68 q-6 5 0 9" stroke="${c.line}" stroke-width="1.3" fill="none" opacity=".45"/>
    </g>
    ${talons([52, 68], 98)}
    <g class="head-tilt">
      <path d="M42 42 Q42 22 60 20 Q78 22 78 42 Q78 56 60 58 Q42 56 42 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M45 36 Q54 30 60 35 L58 40 Q52 36 47 39 Z" fill="${c.body}" opacity=".35"/>
      ${mirror(`<path d="M45 36 Q54 30 60 35 L58 40 Q52 36 47 39 Z" fill="${c.body}" opacity=".35"/>`)}
      <g class="blink"><circle cx="52" cy="42" r="3.3" fill="${INK}"/><circle cx="53.3" cy="40.7" r="1.1" fill="#fff"/>
        <circle cx="68" cy="42" r="3.3" fill="${INK}"/><circle cx="69.3" cy="40.7" r="1.1" fill="#fff"/></g>
      <path d="M54 47 Q60 45 66 47 L64 55 Q62 64 59 61 Q57 60 56 53 Z" fill="${RAPTOR}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 53 Q59 62 60 61 Q57 58 56 53 Z" fill="${BEAKD}"/>
      <ellipse cx="62" cy="49" rx="1.2" ry="0.9" fill="${c.line}"/>
    </g>`,

  // Hawk — perched 3/4 hunter: overhanging fierce brow, hooked beak, folded pointed wing, barred tail
  hawk: (c) => `
    <g class="tail-wag"><path d="M34 82 Q20 90 20 78 Q30 78 40 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M24 80 h14 M26 84 h12" stroke="${c.line}" stroke-width="1.2" opacity=".4"/></g>
    <g class="breathe">
      <path d="M40 84 Q34 54 58 50 Q80 52 78 84 Q60 96 40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 62 Q60 66 70 62 M50 72 Q60 76 70 72" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".8"/>
      <path d="M66 56 Q82 62 80 82 Q72 76 64 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    ${talons([50, 66], 90)}
    <g class="head-tilt">
      <ellipse cx="62" cy="46" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 35 Q73 35 79 45 L74 49 Q66 41 58 43 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M73 41 Q88 42 90 50 Q89 56 83 54 Q85 50 81 48 Q77 46 73 48 Z" fill="${RAPTOR}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M90 50 Q89 56 83 54 Q87 52 88 49 Z" fill="${BEAKD}"/>
      <ellipse cx="79" cy="46" rx="1.1" ry="0.9" fill="${c.line}"/>
      ${eye(68, 45, 3.1, eyeInk(c))}
    </g>`,

  // Falcon — upright sleek flier: dark malar "moustache" stripes, teardrop eye, sharp hooked beak, pointed wings
  falcon: (c) => `
    <g class="tail-wag"><path d="M52 92 Q48 112 60 110 L60 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M52 92 Q48 112 60 110 L60 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}</g>
    <g class="breathe">
      <path d="M60 44 Q82 46 82 76 Q80 98 60 100 Q40 98 38 76 Q38 46 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 58 Q76 60 74 80 Q70 92 60 94 Q50 92 46 80 Q44 60 60 58 Z" fill="${c.shade}"/>
      ${[64, 72, 80].map((y) => `<path d="M50 ${y} q10 4 20 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".35"/>`).join("")}
      <path d="M40 54 Q34 74 42 88 Q46 74 46 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M40 54 Q34 74 42 88 Q46 74 46 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}</g>
    ${talons([54, 66], 100)}
    <g class="head-tilt">
      <path d="M44 38 Q44 20 60 18 Q76 20 76 38 Q76 50 60 52 Q44 50 44 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 40 Q50 50 54 54 Q57 48 56 40 Z" fill="${INK}" opacity=".7"/>
      ${mirror(`<path d="M52 40 Q50 50 54 54 Q57 48 56 40 Z" fill="${INK}" opacity=".7"/>`)}
      <path d="M56 40 Q60 38 64 40 L63 47 Q60 51 58 47 Z" fill="${RAPTOR}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M58 47 Q60 51 61 47 Q60 45 58 47 Z" fill="${BEAKD}"/>
      <g class="blink"><circle cx="53" cy="36" r="3" fill="${INK}"/><circle cx="54.1" cy="34.9" r="1" fill="#fff"/>
        <circle cx="67" cy="36" r="3" fill="${INK}"/><circle cx="68.1" cy="34.9" r="1" fill="#fff"/></g>
    </g>`,

  // Snowy Owl — round smooth face-disc (NO ear tufts), huge forward golden eyes, tiny hooked beak, dappled down
  snowyowl: (c) => `
    <g class="breathe">
      <path d="M32 88 Q30 54 60 52 Q90 54 88 88 Q60 100 32 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[0, 1, 2, 3].map((r) => `<path d="M${42} ${64 + r * 7} q6 5 12 0 q6 5 12 0" stroke="${c.shade}" stroke-width="1.5" fill="none" opacity=".7"/>`).join("")}
      ${["", "s"].map((_, i) => `<path d="M${i ? 66 : 46} 92 l3 6 l3 -6" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="60" cy="44" r="27" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="50" cy="45" rx="12" ry="13" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      ${mirror(`<ellipse cx="50" cy="45" rx="12" ry="13" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>`)}
      <circle cx="50" cy="45" r="6.5" fill="${RAPTOR}"/><circle cx="50" cy="45" r="3.4" fill="${INK}"/><circle cx="52" cy="43" r="1.3" fill="#fff"/>
      <circle cx="70" cy="45" r="6.5" fill="${RAPTOR}"/><circle cx="70" cy="45" r="3.4" fill="${INK}"/><circle cx="72" cy="43" r="1.3" fill="#fff"/>
      <path d="M60 47 Q64 47 63 52 Q60 55 57 52 Q56 47 60 47 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4"/>
      ${[16, 26, 20, 30].map((v, i) => `<circle cx="${i < 2 ? 34 + i * 8 : 78 + (i - 2) * 8}" cy="${34 + (i % 2) * 6}" r="1.6" fill="${c.shade}" opacity=".7"/>`).join("")}
    </g>`,

  // ── PARROTS ───────────────────────────────────────────────────────────────
  // Parrot — upright, big rounded hooked beak, round cheek, curved-down tail, one foot gripping a perch
  parrot: (c) => `
    <line x1="30" y1="102" x2="90" y2="102" stroke="${LEG}" stroke-width="4" stroke-linecap="round"/>
    <g class="tail-wag"><path d="M52 88 Q46 112 58 110 L62 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 88 Q66 108 70 104 L64 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M58 44 Q80 48 80 76 Q78 96 58 98 Q42 96 42 76 Q42 48 58 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 58 Q72 62 70 82 Q66 92 58 94 Q50 92 48 82 Q46 62 58 58 Z" fill="${c.shade}"/>
      <path d="M42 58 Q34 74 42 90 Q46 76 46 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <path d="M54 98 l0 6 M50 104 h8 M50 104 l-3 4 M58 104 l3 4" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="60" cy="40" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="72" cy="42" rx="7" ry="6" fill="${c.shade}" opacity=".8"/>
      <path d="M72 34 Q90 34 88 48 Q86 58 74 56 Q70 52 70 44 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 48 Q84 50 86 46 Q84 56 76 55 Q73 52 74 48 Z" fill="${BEAKD}"/>
      ${eye(66, 38, 3, eyeInk(c))}
    </g>`,

  // Macaw — big parrot: long streaming tail, bare white face-patch with fine lines, massive hooked beak
  macaw: (c) => `
    <g class="tail-wag">
      <path d="M50 84 Q34 112 44 111 L58 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 84 Q52 112 62 110 L62 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M58 46 Q78 50 78 74 Q76 92 58 94 Q42 92 42 74 Q42 50 58 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 56 Q32 74 42 88 Q46 72 46 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 60 q8 4 16 0 M50 70 q8 4 16 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".7"/></g>
    <path d="M54 94 l0 5 M50 99 h8 M50 99 l-3 4 M58 99 l3 4" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="60" cy="40" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M64 32 Q78 30 80 44 Q78 50 66 48 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M66 36 q10 2 12 4 M66 41 q10 0 13 2" stroke="${c.line}" stroke-width="1" opacity=".5" fill="none"/>
      <path d="M74 34 Q94 36 90 52 Q86 62 74 58 Q70 52 70 42 Z" fill="${INK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 50 Q86 52 88 48 Q86 60 76 58 Q72 54 74 50 Z" fill="#3a3f47"/>
      ${eye(70, 38, 3.3, INK)}
    </g>`,

  // Cockatoo — pale, big recurved fanned crest sweeping forward, stout hooked beak, round cheek
  cockatoo: (c) => `
    <g class="tail-wag"><path d="M52 90 Q48 110 60 108 L64 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q80 52 80 78 Q78 98 60 100 Q42 98 40 78 Q40 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 62 Q72 66 70 84 Q66 94 60 96 Q54 94 50 84 Q48 66 60 62 Z" fill="${c.shade}" opacity=".7"/></g>
    ${legs([54, 66], 100, 8)}
    <g class="head-tilt">
      ${[-26, -13, 0, 13, 26].map((a) => `<g transform="rotate(${a} 60 44)"><path d="M60 44 Q56 16 61 11 Q66 17 62 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>`).join("")}
      <circle cx="60" cy="46" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 50 Q60 47 66 50 Q66 60 60 63 Q54 60 54 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 56 Q60 59 64 56 Q63 61 60 62 Q57 61 56 56 Z" fill="${BEAKD}"/>
      ${eye(52, 44, 3.2, eyeInk(c))}${eye(68, 44, 3.2, eyeInk(c))}
    </g>`,

  // ── WATER & SHORE BIRDS ─────────────────────────────────────────────────────
  // Penguin — upright tuxedo: dark back wrapping a pale belly, side flippers, tiny beak, orange webbed feet
  penguin: (c) => `
    <g class="tail-wag">
      <path d="M42 52 Q24 66 30 92 Q40 88 46 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M42 52 Q24 66 30 92 Q40 88 46 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}</g>
    ${[50, 70].map((x) => `<path d="M${x} 100 Q${x} 108 ${x - 7} 108 L${x + 7} 108 Q${x + 2} 103 ${x} 100 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
    <g class="breathe">
      <path d="M60 18 Q84 20 84 62 Q84 100 60 102 Q36 100 36 62 Q36 20 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 36 Q76 38 74 66 Q72 92 60 94 Q48 92 46 66 Q44 38 60 36 Z" fill="${c.shade}"/>
      <path d="M60 22 Q46 24 46 38 Q60 46 74 38 Q74 24 60 22 Z" fill="${c.body}"/></g>
    <g class="head-tilt">
      <path d="M56 40 L64 40 L60 49 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(52, 68, 34, 2.6, eyeInk(c))}
      <path d="M46 34 Q52 30 58 33" stroke="${c.line}" stroke-width="1.3" fill="none" opacity=".4"/>
      ${mirror(`<path d="M46 34 Q52 30 58 33" stroke="${c.line}" stroke-width="1.3" fill="none" opacity=".4"/>`)}
    </g>`,

  // Flamingo — one straight leg + one folded back, plump body high up, long S-neck, down-kinked black-tipped bill
  flamingo: (c) => `
    ${tube("M56 80 L50 108", c.body, c.line, 4)}
    ${tube("M64 80 Q72 92 62 96 L67 108", c.body, c.line, 4)}
    <path d="M50 108 l-5 3 M50 108 l-1 4 M50 108 l4 3 M67 108 l-5 3 M67 108 l-1 4 M67 108 l4 3" stroke="${LEG}" stroke-width="2.2" stroke-linecap="round" fill="none"/>
    <g class="tail-wag"><path d="M40 74 Q26 78 26 68 Q34 70 44 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="22" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 70 Q66 66 72 80 Q60 88 50 82 Z" fill="${c.shade}" opacity=".7"/></g>
    <g class="head-tilt">
      ${tube("M66 66 Q86 62 84 38 Q83 30 74 30", c.body, c.line, 6)}
      <ellipse cx="72" cy="29" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M70 32 Q82 32 85 42 Q86 48 80 47 Q78 42 74 40 Q71 38 70 34 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M80 45 Q85 47 85 42 Q86 48 81 48 Z" fill="${INK}"/>
      ${eye(74, 28, 2.4, eyeInk(c))}
    </g>`,

  // Peacock — huge ocellated fan, small crested head on a slim neck, upright body
  peacock: (c) => `
    <g class="tail-wag">
      ${Array.from({ length: 11 }).map((_, i) => { const a = -50 + i * 10; return `<g transform="rotate(${a} 60 94)"><path d="M60 94 L57 28 Q60 22 63 28 Z" fill="${i % 2 ? c.shade : c.body}" stroke="${c.line}" stroke-width="1.4"/><ellipse cx="60" cy="32" rx="5" ry="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2"/><ellipse cx="60" cy="32" rx="2.8" ry="3.8" fill="${OCE}"/><circle cx="60" cy="33" r="1.7" fill="${INK}"/></g>`; }).join("")}
    </g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="15" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 82 Q60 92 68 82" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".7"/></g>
    ${legs([54, 66], 100, 8)}
    <g class="head-tilt">
      ${tube("M60 74 Q60 58 60 48", c.body, c.line, 7)}
      <ellipse cx="60" cy="44" rx="9" ry="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[-8, 0, 8].map((dx) => `<path d="M${60 + dx * 0.5} 36 L${60 + dx * 1.4} 25" stroke="${c.line}" stroke-width="1.4"/><circle cx="${60 + dx * 1.4}" cy="24" r="2.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("")}
      <path d="M69 44 l10 -1 l-9 4 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 40 Q56 38 58 42 M62 42 Q64 38 68 40" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".8"/>
      ${eyes(55, 65, 43, 2.4, eyeInk(c))}
    </g>`,

  // Swan — graceful S-neck, boat-shaped floating body, arched wing, orange bill with black knob
  swan: (c) => `
    <g class="breathe">
      <path d="M26 84 Q40 66 66 68 Q96 70 98 84 Q94 96 60 96 Q30 96 26 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 74 Q64 60 88 74 Q84 88 62 88 Q50 86 46 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
      ${[0, 1, 2].map((r) => `<path d="M54 ${76 + r * 4} q10 4 22 0" stroke="${c.line}" stroke-width="1.1" fill="none" opacity=".4"/>`).join("")}</g>
    <g class="head-tilt">
      ${tube("M40 78 Q24 66 33 44 Q39 30 52 34", c.body, c.line, 8)}
      <ellipse cx="52" cy="34" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 34 L36 37 L50 41 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M50 30 Q46 28 45 33 Q49 34 52 33 Z" fill="${INK}"/>
      ${eye(53, 32, 2.4, eyeInk(c))}
    </g>`,

  // Pelican — chunky body, short legs, enormous pouched bill with a hooked tip
  pelican: (c) => `
    <g class="tail-wag"><path d="M30 76 Q18 80 18 70 Q26 72 36 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="52" cy="74" rx="26" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 76 Q52 90 66 78 Q64 88 52 90 Q42 88 40 76 Z" fill="${c.shade}" opacity=".7"/></g>
    ${[48, 60].map((x) => `<path d="M${x} 92 l0 8 M${x - 5} 100 h10 M${x - 4} 100 l-2 3 M${x + 4} 100 l2 3" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("")}
    <g class="head-tilt">
      ${tube("M68 66 Q78 54 78 44", c.body, c.line, 9)}
      <circle cx="80" cy="42" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M82 38 L110 42 Q112 45 108 48 L84 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M108 42 Q112 44 108 48 Q106 46 108 42 Z" fill="${BEAKD}"/>
      <path d="M84 48 Q98 50 108 48 Q106 68 88 66 Q82 60 84 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(82, 40, 2.6, eyeInk(c))}
    </g>`,

  // Ostrich — huge fluffy body, very long bare neck, tiny head, big lashed eye, long powerful legs
  ostrich: (c) => `
    ${tube("M54 80 L48 108", c.shade, c.line, 5)}
    ${tube("M64 80 Q72 92 62 96 L68 108", c.shade, c.line, 5)}
    <path d="M42 108 h12 M56 108 h12" stroke="${LEG}" stroke-width="2.6" stroke-linecap="round"/>
    <g class="tail-wag">${pom(36, 66, 12, c.body, c.line, 9, 2)}</g>
    <g class="breathe">${pom(60, 70, 24, c.body, c.line, 11, 2.4)}
      <path d="M50 66 q10 8 20 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".6"/></g>
    <g class="head-tilt">
      ${tube("M60 58 Q68 38 62 22", c.shade, c.line, 5)}
      <ellipse cx="61" cy="20" rx="8" ry="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M61 18 L74 19 Q77 22 74 25 L61 24 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="57" cy="18" r="3.4" fill="${INK}"/><circle cx="58.2" cy="16.8" r="1.1" fill="#fff"/>
      <path d="M53 14 l-3 -2 M55 13 l-2 -3 M57 13 l-1 -3" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
    </g>`,

  // ── SONGBIRDS ───────────────────────────────────────────────────────────────
  // Robin — plump round songbird, round warm breast, cocked tail, fine pointed beak
  robin: (c) => `
    <g class="tail-wag"><path d="M34 82 Q20 84 22 74 Q30 76 40 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="20" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 70 Q58 58 70 70 Q72 86 58 90 Q46 88 46 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M66 62 Q80 66 78 82 Q70 76 62 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 64])}
    <g class="head-tilt">
      <circle cx="66" cy="50" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M78 50 l11 -1 l-11 4 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(68, 48, 3, eyeInk(c))}
    </g>`,

  // Cardinal — sharp pointed crest, thick conical seed-beak, black face-mask, upright
  cardinal: (c) => `
    <g class="tail-wag"><path d="M54 84 Q52 100 60 102 Q68 100 66 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="76" rx="18" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 68 Q66 70 68 86 Q60 92 52 88 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M64 62 Q78 66 76 82 Q68 76 62 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([54, 66])}
    <g class="head-tilt">
      <path d="M53 44 L62 13 L71 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="64" cy="48" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 44 Q52 50 55 61 Q64 64 69 54 Q68 46 58 44 Z" fill="${INK}" opacity=".8"/>
      <path d="M75 47 L88 50 L75 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(66, 46, 3, "#e9edf2")}
    </g>`,

  // Blue Jay — rounded crest, black collar "necklace", barred wing, sturdy straight beak
  bluejay: (c) => `
    <g class="tail-wag"><path d="M52 86 Q50 111 58 114 Q66 110 64 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M54 93 h10 M55 100 h9 M56 107 h8" stroke="${c.line}" stroke-width="1.3" opacity=".45"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="76" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 70 Q60 80 72 70 Q74 78 60 80 Q50 78 50 70 Z" fill="${INK}" opacity=".55"/>
      <path d="M64 60 Q80 64 78 82 Q70 74 62 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 66 h10 M65 72 h11" stroke="${c.shade}" stroke-width="1.6" opacity=".8"/></g>
    ${legs([54, 66])}
    <g class="head-tilt">
      <path d="M54 42 Q55 26 63 24 Q71 27 70 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="64" cy="48" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M78 47 l12 1 l-12 5 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(67, 46, 3, "#e9edf2")}
    </g>`,

  // Crow — sleek glossy all-dark bird, stout straight beak held open mid-caw, alert stance
  crow: (c) => `
    <g class="tail-wag"><path d="M36 86 Q24 106 38 106 L48 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M42 84 Q38 56 60 52 Q82 56 78 84 Q60 96 42 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 62 Q60 66 70 62 M52 72 Q60 76 68 72" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/>
      <path d="M64 58 Q80 62 78 82 Q70 76 62 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([52, 66])}
    <g class="head-tilt">
      <circle cx="62" cy="46" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 42 L92 40 L76 48 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M74 49 L90 52 L76 53 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(64, 44, 3, "#e9edf2")}
    </g>`,

  // Sparrow — small chubby brown bird, short conical beak, pale eyebrow stripe, streaky wing
  sparrow: (c) => `
    <g class="tail-wag"><path d="M40 84 Q30 100 42 100 L50 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="76" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 74 Q58 66 68 74 Q70 86 58 88 Q48 86 48 74 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M62 66 Q74 70 72 82 Q66 76 60 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 70 h9 M62 75 h8" stroke="${c.line}" stroke-width="1.2" opacity=".4"/></g>
    ${legs([54, 64], 90, 10)}
    <g class="head-tilt">
      <circle cx="64" cy="54" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 50 q6 -3 12 0" stroke="${c.shade}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M74 53 l9 1 l-9 4 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(66, 52, 2.8, eyeInk(c))}
    </g>`,

  // Hummingbird — tiny hoverer: needle-thin beak, blurred wing arcs, iridescent gorget, forked tail (float)
  hummingbird: (c) => `
    <g class="tail-wag">
      <path d="M46 60 L24 52 L37 62 L24 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M62 54 Q44 32 28 42 Q46 50 60 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" opacity=".5" stroke-linejoin="round"/>
      <path d="M62 60 Q46 76 30 68 Q48 62 60 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" opacity=".4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="60" rx="15" ry="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M52 62 Q60 70 72 62 Q64 66 52 62 Z" fill="${c.shade}"/>
    </g>
    <g class="head-tilt">
      <circle cx="76" cy="54" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M70 60 Q76 66 82 60 Q76 63 70 60 Z" fill="${TIP}" opacity=".9"/>
      <path d="M83 53 L112 50 L84 57 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${eye(78, 52, 2.6, eyeInk(c))}
    </g>`,

  // Toucan — compact body, oversized banana-curved multi-band beak, big pale eye-ring, gripping a perch
  toucan: (c) => `
    <line x1="26" y1="98" x2="70" y2="98" stroke="${LEG}" stroke-width="4" stroke-linecap="round"/>
    <g class="tail-wag"><path d="M46 84 Q42 104 52 106 Q60 102 58 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M40 84 Q36 56 58 52 Q80 56 76 86 Q58 96 40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 60 Q58 54 70 60 Q72 74 58 78 Q46 74 46 60 Z" fill="${c.shade}"/></g>
    <path d="M46 94 l0 5 M42 99 h8 M42 99 l-3 4 M50 99 l3 4" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="56" cy="44" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M64 32 Q98 28 106 40 Q104 50 96 52 Q78 52 64 48 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M64 34 Q86 32 100 38 Q86 40 66 40 Z" fill="${YEL}"/>
      <path d="M96 40 Q106 40 106 46 Q100 50 94 50 Z" fill="${TIP}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M64 44 Q84 46 100 46" stroke="${c.line}" stroke-width="1.3" fill="none" opacity=".5"/>
      <ellipse cx="52" cy="42" rx="7" ry="8" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      ${eye(52, 42, 3.2, INK)}
    </g>`,

  // Kingfisher — big head, short body & tail, long straight dagger beak, tiny spiky crest, perched on a reed
  kingfisher: (c) => `
    <line x1="72" y1="30" x2="66" y2="108" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".6"/>
    <g class="tail-wag"><path d="M40 86 Q32 98 44 98 L52 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M42 84 Q38 60 60 56 Q80 60 76 86 Q58 96 42 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 66 Q60 60 70 66 Q72 80 58 84 Q48 80 48 66 Z" fill="${c.shade}"/>
      <path d="M64 62 Q78 66 76 82 Q70 76 62 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <path d="M56 94 l0 5 M52 99 h8 M52 99 l-3 4 M60 99 l3 4" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="58" cy="44" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 30 l-2 -8 l6 4 M56 28 l0 -9 l4 6 M62 30 l3 -8 l1 7" stroke="${c.shade}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M48 46 Q34 44 18 42 Q34 50 48 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="54" cy="52" rx="6" ry="4" fill="${c.shade}" opacity=".7"/>
      ${eye(56, 42, 3.1, eyeInk(c))}
    </g>`,

  // Puffin — upright chunky seabird, white cheek discs, big triangular banded beak, bright webbed feet
  puffin: (c) => `
    ${[50, 70].map((x) => `<path d="M${x} 100 Q${x} 108 ${x - 6} 108 L${x + 6} 108 Q${x + 2} 103 ${x} 100 Z" fill="${TIP}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
    <g class="tail-wag"><path d="M34 66 Q22 76 30 90 Q37 84 39 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 22 Q84 26 84 64 Q84 100 60 102 Q36 100 36 64 Q36 26 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 46 Q76 48 74 70 Q72 92 60 94 Q48 92 46 70 Q44 48 60 46 Z" fill="${c.shade}"/></g>
    <g class="head-tilt">
      <ellipse cx="49" cy="40" rx="10" ry="12" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>
      ${mirror(`<ellipse cx="49" cy="40" rx="10" ry="12" fill="${WHT}" stroke="${c.line}" stroke-width="1.4"/>`)}
      <path d="M60 34 L74 38 Q76 48 66 54 Q60 56 54 54 Q44 48 46 38 Z" fill="${TIP}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M54 36 Q60 34 66 36 L64 52 Q60 55 56 52 Z" fill="${YEL}"/>
      <path d="M56 42 Q60 44 64 42 M55 48 Q60 50 65 48" stroke="${BEAKD}" stroke-width="1.4" fill="none"/>
      ${eyes(49, 71, 40, 2.6, INK)}
    </g>`,
};

export const ROSTER_BIRDS = [
  { n: "Bald Eagle", e: "🦅", tier: 3, float: false },
  { n: "Hawk", e: "🦅", tier: 2, float: false },
  { n: "Falcon", e: "🦅", tier: 2, float: false },
  { n: "Snowy Owl", e: "🦉", tier: 3, float: false },
  { n: "Parrot", e: "🦜", tier: 2, float: false },
  { n: "Macaw", e: "🦜", tier: 3, float: false },
  { n: "Cockatoo", e: "🦜", tier: 2, float: false },
  { n: "Penguin", e: "🐧", tier: 1, float: false },
  { n: "Flamingo", e: "🦩", tier: 2, float: false },
  { n: "Peacock", e: "🦚", tier: 3, float: false },
  { n: "Swan", e: "🦢", tier: 2, float: false },
  { n: "Pelican", e: "🦤", tier: 2, float: false },
  { n: "Ostrich", e: "🦤", tier: 2, float: false },
  { n: "Robin", e: "🐦", tier: 1, float: false },
  { n: "Cardinal", e: "🐦", tier: 1, float: false },
  { n: "Blue Jay", e: "🐦", tier: 1, float: false },
  { n: "Crow", e: "🐦‍⬛", tier: 1, float: false },
  { n: "Sparrow", e: "🐦", tier: 1, float: false },
  { n: "Hummingbird", e: "🐦", tier: 2, float: true },
  { n: "Toucan", e: "🦜", tier: 3, float: false },
  { n: "Kingfisher", e: "🐦", tier: 2, float: false },
  { n: "Puffin", e: "🐧", tier: 2, float: false },
];
