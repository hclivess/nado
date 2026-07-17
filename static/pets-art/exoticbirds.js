// exoticbirds.js — BESPOKE hand-drawn SVG art for TROPICAL & EXOTIC BIRDS (NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,62), within x,y ∈ [8,112].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/belly/spots), c.line (outline stroke).
// Fixed warm accents allowed for beaks/legs/bare skin (BEAK/DAGGER/LEG/RED/…); nose/eyes = INK/eyeInk.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const BEAK = "#f2a03b";   // orange beak / bill
const BEAKD = "#d97b2c";  // darker beak shading / hook underside
const DAGGER = "#f2c94c"; // yellow dagger bill (heron / crane)
const LEG = "#e79a3a";    // scaly legs / toes
const WHT = "#fbf6ee";    // eye-ring / cheek / plume highlight (not coat — a highlight)
const TIP = "#e0564d";    // red flash (crest / belly / cheek patch)
const RED = "#d8534b";    // bare-skin red (wattles, crowns, face patches)
const SPOON = "#cfd2d8";  // grey spatulate spoonbill tip
const YEL = "#f4c84a";    // yellow beak (quetzal)

// perched songbird legs: thin scaly legs with three splayed toes
const legs = (xs, y = 90, h = 12) => xs.map((x) =>
  `<path d="M${x} ${y} l0 ${h} M${x} ${y + h} l-4 4 M${x} ${y + h} l4 4 M${x} ${y + h} l0 5" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");
// long wading legs: slender, softly kinked knee, splayed forward toes at y≈110
const wlegs = (xs, top, y = 110) => xs.map((x) =>
  `<path d="M${x} ${top} Q${x - 3} ${((top + y) / 2).toFixed(1)} ${x} ${y - 6} Q${x + 1} ${y - 2} ${x} ${y}" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>` +
  `<path d="M${x} ${y} l-6 4 M${x} ${y} l6 4 M${x} ${y} l-2 5" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");

export const ART_EXOTICBIRDS = {
  // ── PARAKEETS & SMALL PARROTS ───────────────────────────────────────────────
  // Budgie — small perched parakeet: barred forehead & wing scalloping, cere+hook beak, throat spots, long tail
  budgie: (c) => `
    <line x1="34" y1="106" x2="86" y2="106" stroke="${LEG}" stroke-width="4" stroke-linecap="round"/>
    <g class="tail-wag"><path d="M55 88 Q50 116 58 114 L62 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 88 Q66 112 70 108 L64 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="72" rx="17" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 60 Q56 56 63 62 Q67 80 57 88 Q47 82 46 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      ${[64, 70, 76, 82].map((y) => `<path d="M48 ${y} q7 3 15 0" stroke="${c.line}" stroke-width="1" fill="none" opacity=".4"/>`).join("")}</g>
    <path d="M54 100 l0 6 M50 106 h8 M50 106 l-3 3 M58 106 l3 3" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="60" cy="46" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[38, 41, 44].map((y) => `<path d="M50 ${y} q10 -3 20 0" stroke="${c.line}" stroke-width="0.9" fill="none" opacity=".4"/>`).join("")}
      <path d="M60 50 Q67 50 66 56 Q62 60 58 56 Q56 50 60 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="51" cy="57" r="2" fill="${INK}" opacity=".45"/><circle cx="69" cy="57" r="2" fill="${INK}" opacity=".45"/>
      ${eyes(53, 67, 45, 2.8, eyeInk(c))}
    </g>`,

  // Lovebird — tiny stocky parrot: oversized round head, bold white eye-ring, stubby hooked beak, short tail
  lovebird: (c) => `
    <line x1="36" y1="104" x2="84" y2="104" stroke="${LEG}" stroke-width="4" stroke-linecap="round"/>
    <g class="tail-wag"><path d="M52 84 Q48 100 58 98 L62 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="72" rx="20" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 60 Q73 64 71 80 Q66 90 60 90 Q54 90 50 80 Q48 64 60 60 Z" fill="${c.shade}" opacity=".65"/></g>
    <path d="M54 90 l0 6 M50 96 h8 M50 96 l-3 3 M58 96 l3 3" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="60" cy="44" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 36 Q60 30 68 36 Q66 44 60 44 Q54 44 52 36 Z" fill="${TIP}" opacity=".55"/>
      <ellipse cx="66" cy="43" rx="5.5" ry="6" fill="${WHT}" stroke="${c.line}" stroke-width="1.3"/>
      <path d="M70 40 Q80 40 78 50 Q75 56 68 54 Q65 50 66 44 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M68 50 Q76 51 78 47 Q76 55 69 54 Z" fill="${BEAKD}"/>
      ${eye(66, 43, 3, INK)}
    </g>`,

  // Cockatiel — slim: thin swept-back pointed crest, round orange cheek disc, small grey hook beak, long tail
  cockatiel: (c) => `
    <g class="tail-wag"><path d="M54 88 Q50 116 58 114 L62 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M59 88 Q64 114 68 110 L63 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="16" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 64 Q55 60 61 66 Q64 82 55 88 Q47 84 46 64 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M44 66 q4 -2 8 0 M44 70 q4 -2 8 0" stroke="${WHT}" stroke-width="2" fill="none" stroke-linecap="round"/></g>
    ${legs([54, 64], 92, 10)}
    <g class="head-tilt">
      ${[-30, -18, -6].map((a, i) => `<g transform="rotate(${a} 58 40)"><path d="M58 40 Q${52 - i * 2} 10 ${58 - i} 8 Q${61 - i} 20 60 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/></g>`).join("")}
      <circle cx="60" cy="44" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="54" cy="50" r="5" fill="${TIP}" opacity=".9" stroke="${c.line}" stroke-width="1"/>
      <path d="M60 48 Q70 48 68 57 Q64 62 59 59 Q57 53 60 48 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(62, 44, 3, eyeInk(c))}
    </g>`,

  // ── FINCHES & SONGBIRDS ─────────────────────────────────────────────────────
  // Canary — plump round songbird caught mid-song: raised head, open conical beak, cheerful curve
  canary: (c) => `
    <g class="tail-wag"><path d="M40 86 Q30 104 42 102 L50 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="18" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 72 Q58 64 68 72 Q70 86 58 90 Q48 88 48 72 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M62 64 Q76 68 74 82 Q68 76 60 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${legs([54, 64], 90, 11)}
    <g class="head-tilt">
      <circle cx="62" cy="50" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 48 L88 45 L75 51 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M74 52 L86 54 L75 55 Z" fill="${BEAKD}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M60 40 q2 -6 6 -4" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".7"/>
      ${eye(64, 48, 3, eyeInk(c))}
    </g>`,

  // Finch — compact seed-eater: heavy conical beak, streaky folded wing, notched forked tail
  finch: (c) => `
    <g class="tail-wag"><path d="M38 86 Q30 104 40 100 L48 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 88 Q40 106 50 102 L52 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="18" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 70 Q58 64 66 70 Q68 84 57 88 Q48 84 48 70 Z" fill="${c.shade}" opacity=".6"/>
      ${[68, 74, 80].map((y) => `<path d="M50 ${y} q8 3 16 0" stroke="${c.line}" stroke-width="1" fill="none" opacity=".4"/>`).join("")}</g>
    ${legs([54, 64], 90, 11)}
    <g class="head-tilt">
      <circle cx="64" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 46 Q64 42 72 46 Q64 50 56 46 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M74 49 L88 52 L74 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M74 52 h13" stroke="${c.line}" stroke-width="0.8" opacity=".5"/>
      ${eye(66, 50, 2.9, eyeInk(c))}
    </g>`,

  // Weaverbird — songbird beside its hanging woven grass-ball nest with a round entry hole; conical beak
  weaverbird: (c) => `
    <g class="tail-wag">
      <line x1="38" y1="10" x2="40" y2="22" stroke="${LEG}" stroke-width="1.6"/>
      <path d="M30 22 Q26 42 40 54 Q56 62 52 42 Q50 28 44 22 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".9"/>
      ${[0, 1, 2, 3].map((i) => `<path d="M29 ${28 + i * 7} Q40 ${32 + i * 7} 51 ${28 + i * 7}" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
      ${[0, 1, 2].map((i) => `<path d="M${34 + i * 6} 22 Q${36 + i * 6} 40 ${34 + i * 6} 54" fill="none" stroke="${c.line}" stroke-width="1" opacity=".45"/>`).join("")}
      <ellipse cx="41" cy="53" rx="5" ry="3.4" fill="${INK}" opacity=".6"/></g>
    <g class="tail-wag"><path d="M80 84 Q92 102 80 100 L72 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="72" cy="74" rx="16" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M62 72 Q72 64 82 72 Q84 84 72 88 Q62 86 62 72 Z" fill="${c.shade}" opacity=".55"/></g>
    ${legs([68, 78], 88, 10)}
    <g class="head-tilt">
      <circle cx="66" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 46 Q66 42 72 46 Q66 50 60 46 Z" fill="${INK}" opacity=".5"/>
      <path d="M55 52 L42 49 L55 56 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M55 52 h13" stroke="${c.line}" stroke-width="0.8" opacity=".5"/>
      ${eye(63, 50, 2.9, eyeInk(c))}
    </g>`,

  // ── TROPICAL JEWELS ─────────────────────────────────────────────────────────
  // Quetzal — fluffy helmet-crest, short yellow beak, crimson belly, twin very-long streaming tail plumes
  quetzal: (c) => `
    <g class="tail-wag">
      <path d="M56 84 Q46 108 52 116 Q58 106 60 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M62 84 Q70 106 66 118 Q60 108 60 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M54 92 q-3 8 2 12 M64 92 q4 8 -1 12" stroke="${c.line}" stroke-width="1" fill="none" opacity=".4"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="18" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 74 Q60 70 68 74 Q70 88 60 92 Q52 90 52 74 Z" fill="${TIP}" opacity=".8"/>
      ${[60, 66, 72].map((y) => `<path d="M48 ${y} q12 4 24 0" stroke="${c.line}" stroke-width="1" fill="none" opacity=".35"/>`).join("")}</g>
    ${legs([54, 66], 92, 9)}
    <g class="head-tilt">
      <circle cx="60" cy="44" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${pom(60, 34, 11, c.body, c.line, 9, 2)}
      <path d="M72 44 L84 42 L73 48 Z" fill="${YEL}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(65, 43, 3, eyeInk(c))}
    </g>`,

  // Bird of Paradise — displaying: fan of ornate flank plumes + two long looping wire tails, small crowned head
  birdofparadise: (c) => `
    <g class="tail-wag">
      ${[0, 1, 2, 3, 4].map((i) => { const a = -40 + i * 20; return `<g transform="rotate(${a} 60 66)"><path d="M60 66 Q${44 - i} ${(44 - i * 2)} ${52 - i} 30 Q60 44 60 66 Z" fill="${i % 2 ? c.shade : TIP}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round" opacity=".92"/></g>`; }).join("")}
    </g>
    <g class="tail-wag">
      <path d="M54 70 Q40 92 60 96 Q52 88 58 72 Z" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M66 70 Q84 90 62 96 Q72 86 62 72 Z" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="42" cy="94" r="2.4" fill="${c.shade}"/><circle cx="82" cy="92" r="2.4" fill="${c.shade}"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="64" rx="15" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 60 q8 4 16 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/></g>
    <g class="head-tilt">
      <circle cx="60" cy="42" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 36 Q60 30 68 36 Q60 42 52 36 Z" fill="${TIP}" opacity=".85"/>
      <path d="M60 44 L52 30 M60 44 L68 30" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <path d="M56 34 L44 32 L56 38 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(58, 34, 2.6, eyeInk(c))}
    </g>`,

  // Hornbill — profile: huge down-curved beak topped by a bold casque ridge, long lashes, chunky body
  hornbill: (c) => `
    <g class="tail-wag"><path d="M34 84 Q22 104 34 104 L46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M30 90 h14" stroke="${WHT}" stroke-width="2" opacity=".7"/></g>
    <g class="breathe">
      <path d="M40 84 Q34 58 58 54 Q80 58 76 86 Q58 96 40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 62 Q58 56 68 62 Q70 78 57 84 Q46 78 46 62 Z" fill="${c.shade}"/></g>
    ${legs([52, 66], 92, 10)}
    <g class="head-tilt">
      <circle cx="58" cy="42" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M64 34 Q104 30 108 50 Q106 58 96 58 Q76 58 64 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M66 34 Q98 30 106 42 Q100 26 78 28 Q70 30 66 34 Z" fill="${TIP}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 46 Q86 50 104 50" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".5"/>
      <path d="M50 34 l-3 -4 M54 32 l-2 -5 M58 32 l0 -5" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
      ${eye(56, 42, 3, eyeInk(c))}
    </g>`,

  // ── BIG FLIGHTLESS ──────────────────────────────────────────────────────────
  // Cassowary — shaggy body, tall bony head casque, blue neck, twin hanging red wattles, powerful legs
  cassowary: (c) => `
    ${wlegs([54, 66], 78)}
    <g class="tail-wag">${pom(40, 66, 12, c.body, c.line, 10, 2.2)}</g>
    <g class="breathe">${pom(60, 72, 22, c.body, c.line, 12, 2.4)}
      <path d="M50 68 q10 8 20 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".5"/></g>
    <g class="head-tilt">
      ${tube("M62 60 Q70 44 66 30", c.shade, c.line, 7)}
      <path d="M60 46 q6 3 4 8 M66 44 q6 3 4 8" stroke="${RED}" stroke-width="3" fill="none" stroke-linecap="round"/>
      <ellipse cx="64" cy="26" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 20 Q64 6 72 12 Q72 22 66 24 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M70 26 L82 27 Q85 30 82 33 L70 31 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(62, 24, 2.8, eyeInk(c))}
    </g>`,

  // Emu — big shaggy droopy plumage, feathered neck strands, tiny head, dark stubby bill, long legs
  emu: (c) => `
    ${wlegs([54, 66], 76)}
    <g class="breathe">
      ${pom(60, 70, 24, c.body, c.line, 14, 2.4)}
      ${[52, 60, 68].map((x) => `<path d="M${x} 52 Q${x - 2} 66 ${x} 82" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".55"/>`).join("")}</g>
    <g class="head-tilt">
      ${tube("M60 56 Q66 38 60 22", c.body, c.line, 6)}
      <path d="M55 40 q3 6 5 0 M60 46 q3 6 5 0" stroke="${c.shade}" stroke-width="1.2" fill="none" opacity=".5"/>
      <ellipse cx="59" cy="20" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M59 18 L72 19 Q75 22 72 25 L59 24 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="55" cy="18" r="3.2" fill="${INK}"/><circle cx="56.1" cy="16.9" r="1" fill="#fff"/>
    </g>`,

  // Kiwi — round pear body, hair-like shaggy plumage, no visible wings, stubby legs, very long thin down-curved beak
  kiwi: (c) => `
    <g class="breathe">
      <path d="M40 66 Q40 40 66 40 Q92 42 92 70 Q92 96 64 96 Q42 96 40 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<path d="M${44 + i * 9} 44 q-3 -7 2 -10" stroke="${c.shade}" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".6"/>`).join("")}
      <path d="M52 70 q14 8 30 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".5"/></g>
    <path d="M54 94 l0 8 M50 102 h8 M50 102 l-3 4 M58 102 l3 4" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <path d="M70 94 l0 8 M66 102 h8 M66 102 l-3 4 M74 102 l3 4" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M42 58 Q20 60 12 72 Q22 74 40 70" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
      <path d="M42 58 Q20 60 12 72 Q22 74 40 70" fill="none" stroke="${BEAKD}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M40 60 l-6 -3 M40 63 l-7 0 M40 66 l-6 3" stroke="${c.line}" stroke-width="1" stroke-linecap="round" opacity=".6"/>
      ${eye(48, 58, 2.6, eyeInk(c))}
    </g>`,

  // Roadrunner — horizontal dash: shaggy raised crest, long cocked tail, running stride, long straight beak
  roadrunner: (c) => `
    <g class="tail-wag"><path d="M40 66 Q16 50 10 58 Q14 66 34 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 56 h14 M20 62 h12" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="66" rx="24" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 68 Q58 76 74 68 Q72 78 58 80 Q46 78 44 68 Z" fill="${c.shade}" opacity=".65"/>
      ${[58, 66, 74].map((x) => `<path d="M${x} 56 q-2 8 0 16" stroke="${c.line}" stroke-width="1" fill="none" opacity=".4"/>`).join("")}</g>
    <path d="M50 78 L44 96 M44 96 l-5 4 M44 96 l5 4" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <path d="M66 78 L76 96 M76 96 l-5 4 M76 96 l5 4" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <circle cx="78" cy="52" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 42 l-2 -8 l5 5 M80 41 l2 -8 l2 7" stroke="${c.shade}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      <path d="M88 50 L108 48 L88 55 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M70 47 q6 -2 8 1" stroke="${RED}" stroke-width="1.6" fill="none" opacity=".7"/>
      ${eye(82, 50, 3, eyeInk(c))}
    </g>`,

  // ── LONG-LEGGED WADERS ──────────────────────────────────────────────────────
  // Heron — tall wader: long S-neck, slim body, trailing head plume, long yellow dagger bill
  heron: (c) => `
    ${wlegs([54, 66], 74)}
    <g class="tail-wag"><path d="M40 66 Q26 72 26 62 Q34 64 44 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M38 64 Q46 48 68 52 Q84 56 80 68 Q70 78 52 76 Q40 74 38 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 60 q14 4 26 2" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".6"/>
      <path d="M60 66 q10 2 18 0 M58 70 q10 2 16 0" stroke="${c.line}" stroke-width="1" fill="none" opacity=".35"/></g>
    <g class="head-tilt">
      ${tube("M66 56 Q60 40 70 30 Q74 24 82 24", c.body, c.line, 6)}
      <ellipse cx="82" cy="24" rx="9" ry="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M84 22 L108 26 Q110 28 108 30 L84 28 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M78 20 Q92 14 100 16 Q90 20 82 24" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 23, 2.6, eyeInk(c))}
    </g>`,

  // Egret — slender delicate wader: thin neck, wispy trailing breeding plumes, fine orange dagger bill
  egret: (c) => `
    ${wlegs([56, 66], 72)}
    <g class="tail-wag">
      <path d="M42 62 Q22 60 14 66 Q26 66 40 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" opacity=".8" stroke-linejoin="round"/>
      <path d="M42 66 Q24 68 16 74 Q28 72 42 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" opacity=".7" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M40 66 Q46 50 66 54 Q80 58 76 68 Q66 76 52 74 Q42 72 40 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 62 q12 3 22 2" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/></g>
    <g class="head-tilt">
      ${tube("M64 58 Q56 40 66 28 Q70 22 78 24", c.body, c.line, 5)}
      <ellipse cx="80" cy="24" rx="8" ry="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M82 22 L106 25 Q108 27 106 29 L82 27 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(82, 23, 2.4, eyeInk(c))}
    </g>`,

  // Ibis — long legs & neck ending in a long slender down-curved sickle bill
  ibis: (c) => `
    ${wlegs([54, 66], 72)}
    <g class="tail-wag"><path d="M40 64 Q28 70 28 60 Q34 62 44 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="62" rx="20" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 60 q12 4 22 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/></g>
    <g class="head-tilt">
      ${tube("M64 52 Q66 38 76 30", c.body, c.line, 6)}
      <ellipse cx="78" cy="28" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M84 28 Q98 30 100 44 Q102 52 98 52 Q96 44 88 38 Q82 34 82 30 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(78, 27, 2.6, eyeInk(c))}
    </g>`,

  // Stork — bulky wader, dark wing shawl, thick straight red bill, long neck & legs
  stork: (c) => `
    ${wlegs([54, 66], 76)}
    <g class="tail-wag"><path d="M38 68 Q26 62 24 72 Q32 72 42 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M36 68 Q42 50 64 52 Q84 56 80 72 Q68 82 50 80 Q38 78 36 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 74 Q60 84 78 74 Q74 82 60 84 Q46 82 44 74 Z" fill="${INK}" opacity=".4"/></g>
    <g class="head-tilt">
      ${tube("M64 54 Q62 38 72 28", c.body, c.line, 7)}
      <ellipse cx="74" cy="26" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M80 24 L106 22 Q109 27 106 31 L80 30 Z" fill="${RED}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(74, 25, 2.6, eyeInk(c))}
    </g>`,

  // Crane — stately wader: long neck, red crown cap, dagger bill, drooping bustle of tail plumes
  crane: (c) => `
    ${wlegs([54, 66], 74)}
    <g class="tail-wag">
      <path d="M36 62 Q20 74 30 82 Q40 74 46 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M34 66 Q22 78 32 84" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="60" rx="20" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 58 q12 4 22 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".5"/></g>
    <g class="head-tilt">
      ${tube("M64 50 Q68 34 74 24", c.body, c.line, 6)}
      <ellipse cx="76" cy="22" rx="8" ry="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M72 16 Q76 10 82 15 Q80 20 74 20 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M82 22 L104 24 Q106 26 104 28 L82 26 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(78, 22, 2.4, eyeInk(c))}
    </g>`,

  // Spoonbill — wader with the signature long flat bill flaring into a broad rounded spatula
  spoonbill: (c) => `
    ${wlegs([54, 66], 72)}
    <g class="tail-wag"><path d="M40 62 Q28 68 28 58 Q34 60 44 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="60" rx="20" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 66 q10 5 20 0" stroke="${TIP}" stroke-width="2" fill="none" opacity=".5"/></g>
    <g class="head-tilt">
      ${tube("M64 52 Q64 38 74 30", c.body, c.line, 6)}
      <ellipse cx="76" cy="28" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M80 30 Q92 34 96 42" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M80 30 Q92 34 96 42" fill="none" stroke="${SPOON}" stroke-width="3.2" stroke-linecap="round"/>
      <ellipse cx="98" cy="46" rx="8" ry="6" fill="${SPOON}" stroke="${c.line}" stroke-width="2" transform="rotate(28 98 46)"/>
      ${eye(76, 27, 2.6, eyeInk(c))}
    </g>`,

  // ── ORNAMENTAL & ODDBALLS ───────────────────────────────────────────────────
  // Pheasant — chunky ground bird: red bare-face patch, ear-tufts, and a very long sweeping pointed tail
  pheasant: (c) => `
    <g class="tail-wag">
      <path d="M42 70 Q14 88 8 100 Q20 96 46 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 74 Q20 90 12 100 M46 78 Q26 92 20 100" stroke="${c.line}" stroke-width="1" fill="none" opacity=".45"/>
      <path d="M40 72 Q16 84 10 94" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".7"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="22" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 70 Q62 80 76 70 Q74 82 60 84 Q48 82 48 70 Z" fill="${c.shade}"/>
      ${[54, 62, 70].map((x) => `<circle cx="${x}" cy="72" r="1.6" fill="${INK}" opacity=".4"/>`).join("")}</g>
    ${legs([56, 68], 86, 12)}
    <g class="head-tilt">
      <circle cx="80" cy="54" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M84 46 l3 -6 M88 50 l6 -3" stroke="${c.shade}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      <ellipse cx="82" cy="56" rx="6" ry="4.5" fill="${RED}" opacity=".85"/>
      <path d="M90 53 L102 51 L90 57 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(82, 52, 2.8, INK)}
    </g>`,

  // Hoatzin — spiky punk fan-crest, bright bare blue face, red eye, chunky body — the "stinkbird"
  hoatzin: (c) => `
    <g class="tail-wag"><path d="M38 84 Q26 106 40 104 L50 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 88 Q40 106 52 102 L54 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M42 82 Q38 56 58 52 Q80 56 78 84 Q60 96 42 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 60 Q60 54 70 60 Q72 78 58 84 Q48 78 50 60 Z" fill="${TIP}" opacity=".7"/></g>
    ${legs([54, 66], 90, 10)}
    <g class="head-tilt">
      ${[-38, -24, -10, 4, 18].map((a) => `<g transform="rotate(${a} 60 40)"><path d="M60 40 L58 12 L64 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/></g>`).join("")}
      <circle cx="62" cy="44" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 44 Q46 38 50 32 Q58 34 58 44 Q56 50 50 44 Z" fill="#5aa0d0" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M74 44 L86 46 L74 50 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="59" cy="42" r="3" fill="${RED}"/><circle cx="60" cy="41" r="1" fill="#fff"/>
    </g>`,

  // Kookaburra — big-headed kingfisher kin: dark eye-mask, huge dagger bill agape mid-laugh, stocky, short tail
  kookaburra: (c) => `
    <g class="tail-wag"><path d="M40 84 Q30 100 44 98 L52 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M36 90 h14 M38 95 h12" stroke="${c.shade}" stroke-width="1.4" opacity=".7"/></g>
    <g class="breathe">
      <path d="M42 84 Q40 60 60 56 Q80 60 78 84 Q60 94 42 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 66 Q60 60 70 66 Q72 80 60 84 Q50 80 50 66 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M64 62 Q80 66 78 84 Q70 76 62 76 Z" fill="${TIP}" opacity=".45" stroke="${c.line}" stroke-width="1.4"/></g>
    ${legs([54, 66], 92, 9)}
    <g class="head-tilt">
      <circle cx="56" cy="44" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 40 Q56 34 68 42 Q56 44 42 44 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M58 40 L96 36 Q100 40 96 44 L58 47 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 47 L94 47 Q98 50 94 52 L58 52 Z" fill="${BEAKD}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M46 38 Q44 44 48 50" stroke="${INK}" stroke-width="2" fill="none" opacity=".5"/>
      ${eye(50, 42, 3.2, eyeInk(c))}
    </g>`,
};

export const ROSTER_EXOTICBIRDS = [
  { n: "Budgie", e: "🦜", tier: 1, float: false },
  { n: "Lovebird", e: "🦜", tier: 1, float: false },
  { n: "Cockatiel", e: "🦜", tier: 2, float: false },
  { n: "Canary", e: "🐤", tier: 1, float: false },
  { n: "Finch", e: "🐦", tier: 1, float: false },
  { n: "Weaverbird", e: "🐦", tier: 1, float: false },
  { n: "Quetzal", e: "🦜", tier: 3, float: false },
  { n: "Bird of Paradise", e: "🐦", tier: 3, float: true },
  { n: "Hornbill", e: "🦜", tier: 2, float: false },
  { n: "Cassowary", e: "🦤", tier: 2, float: false },
  { n: "Emu", e: "🦤", tier: 2, float: false },
  { n: "Kiwi", e: "🐦", tier: 2, float: false },
  { n: "Roadrunner", e: "🐦", tier: 2, float: false },
  { n: "Heron", e: "🐦", tier: 2, float: false },
  { n: "Egret", e: "🐦", tier: 2, float: false },
  { n: "Ibis", e: "🐦", tier: 2, float: false },
  { n: "Stork", e: "🐦", tier: 2, float: false },
  { n: "Crane", e: "🐦", tier: 2, float: false },
  { n: "Spoonbill", e: "🦩", tier: 2, float: false },
  { n: "Pheasant", e: "🐦", tier: 2, float: false },
  { n: "Hoatzin", e: "🐦", tier: 2, float: false },
  { n: "Kookaburra", e: "🐦", tier: 2, float: false },
];
