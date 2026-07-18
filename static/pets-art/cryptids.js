// pets-art/cryptids.js — BESPOKE hand-drawn SVG art for CRYPTIDS (folklore monsters, cute-creepy) for NADO Pets.
// Each entry: slug -> (c) => "<svg inner markup>" for viewBox 0 0 120 120, creature centered ~ (60,64),
// within x,y ∈ [8,114]. HOUSE STYLE: ONE continuous body+head silhouette (fill c.body, stroke c.line 3.2,
// linejoin round); appendages (wings/tails/limbs) tuck behind or overlap ≥6px so NOTHING floats; two-tone
// shading (pale belly() patch + darker c.shade accent); big glossy ceye() face. Colours come from the coat
// object c (palette applied at hatch) — only universal accents (horns/hooves/beaks #f2c94c/#f2a03b, teeth
// #fff, ink nose/eyes) and glowing cryptid eyes (#eafff4 / #ff5d5d) are fixed. Animate: torso .breathe,
// head .head-tilt, wings/tails/ears .tail-wag. Fliers/lake-serpents set float:true.
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile } from "../pets-draw.js";

const HORN = "#f2c94c", HOOF = "#f2a03b", TOOTH = "#ffffff", GLOW = "#eafff4", RED = "#ff5d5d";

// a big glowing cryptid eye (colour = GLOW or RED) with catchlight; blinks with the page CSS
const glow = (x, y, r, col) => `<circle cx="${x}" cy="${y}" r="${(r + 2).toFixed(1)}" fill="${col}" opacity=".22"/><g class="blink"><circle cx="${x}" cy="${y}" r="${r}" fill="${col}" stroke="${INK}" stroke-width="1"/><circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.35).toFixed(1)}" r="${(r * 0.32).toFixed(1)}" fill="#fff"/></g>`;

export const ART_CRYPTIDS = {
  // ── Bigfoot — classic tall shaggy ape, heavy brow, broad shoulders, big feet, arms at sides (front) ──
  bigfoot: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M34 60 Q18 66 20 84 Q22 96 32 96 Q30 84 40 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M86 60 Q102 66 100 84 Q98 96 88 96 Q90 84 80 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 112 C40 112 30 98 30 78 C30 60 38 50 46 46 C42 40 42 30 50 26 C54 24 56 24 60 24 C64 24 66 24 70 26 C78 30 78 40 74 46 C82 50 90 60 90 78 C90 98 80 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 108 C46 108 40 96 42 82 Q60 88 78 82 Q80 96 60 108 Z" fill="${B}"/>
      <ellipse cx="46" cy="106" rx="8" ry="5" fill="${c.shade}"/><ellipse cx="74" cy="106" rx="8" ry="5" fill="${c.shade}"/>
      <ellipse cx="60" cy="44" rx="16" ry="15" fill="${B}"/>
      <path d="M48 36 q6 -3 11 0 M61 36 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="47" rx="5" ry="3.4" fill="${c.shade}"/>
      <ellipse cx="57.6" cy="46.6" rx="1.1" ry="1.4" fill="${INK}"/><ellipse cx="62.4" cy="46.6" rx="1.1" ry="1.4" fill="${INK}"/>
      <path d="M52 55 q8 5 16 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${ceye(52, 41, 3.4)}${ceye(68, 41, 3.4)}
    </g>`; },

  // ── Chupacabra — gaunt hairless dog, dorsal spine crest, glowing red eyes, fangs, ratty tail (front) ──
  chupacabra: (c) => { const B = belly(c), D = deepen(c.body, 0.24); return `
    ${floorShadow(60, 110, 25)}
    <g class="tail-wag">
      <path d="M40 46 L30 24 L48 40 Z M80 46 L90 24 L72 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${tube("M78 94 Q98 94 98 76", c.body, c.line, 4)}
    </g>
    <g class="breathe">
      <path d="M60 108 C42 108 36 92 39 78 C41 68 46 62 52 60 C46 54 44 44 50 38 C54 33 56 32 60 32 C64 32 66 33 70 38 C76 44 74 54 68 60 C74 62 79 68 81 78 C84 92 78 108 60 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="84" rx="15" ry="18" fill="${B}"/>
      <path d="M46 74 q6 6 0 12 M74 74 q-6 6 0 12 M41 86 q5 4 0 9 M79 86 q-5 4 0 9" fill="none" stroke="${D}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
      ${[[53, 34, 58, 13, 63, 34], [45, 44, 49, 26, 54, 44], [66, 44, 71, 26, 75, 44], [48, 52, 52, 38, 56, 52], [64, 52, 68, 38, 72, 52]].map(([a, b, x, y, e, f]) => `<path d="M${a} ${b} L${x} ${y} L${e} ${f} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
      <ellipse cx="60" cy="48" rx="16" ry="13" fill="${B}"/>
      <path d="M60 52 l-4 5 h8 Z" fill="${INK}"/>
      <path d="M48 60 q12 9 24 0 q-4 6 -12 6 q-8 0 -12 -6 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 61 l2 6 l2 -6 Z M64 61 l2 6 l2 -6 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      ${glow(52, 44, 3.4, RED)}${glow(68, 44, 3.4, RED)}
    </g>`; },

  // ── Mothman — fuzzy moth-humanoid, huge glowing red eyes, feathery antennae, broad moth wings (float) ──
  mothman: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      <path d="M54 58 Q28 40 12 52 Q22 60 34 60 Q18 68 22 86 Q42 80 56 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M66 58 Q92 40 108 52 Q98 60 86 60 Q102 68 98 86 Q78 80 64 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <circle cx="30" cy="60" r="3.4" fill="${B}"/><circle cx="90" cy="60" r="3.4" fill="${B}"/>
      <circle cx="34" cy="80" r="2.6" fill="${B}"/><circle cx="86" cy="80" r="2.6" fill="${B}"/>
    </g>
    <g class="breathe">
      <path d="M46 44 C46 30 52 24 60 24 C68 24 74 30 74 44 C80 48 82 62 80 76 C82 92 74 106 60 106 C46 106 38 92 40 76 C38 62 40 48 46 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="78" rx="11" ry="18" fill="${B}"/>
      <path d="M52 70 h16 M52 80 h16 M53 90 h14" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
      <path d="M54 30 Q44 20 38 16 M66 30 Q76 20 82 16" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="38" cy="16" r="2.8" fill="${c.shade}"/><circle cx="82" cy="16" r="2.8" fill="${c.shade}"/>
      ${glow(51, 44, 5.6, RED)}${glow(69, 44, 5.6, RED)}
      <path d="M55 54 q5 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Jackalope — cute rabbit with a forked antler crown, long ears, twitchy nose, fluffy tail (sit) ──
  jackalope: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 24)}
    <g class="tail-wag">
      ${pom(84, 96, 8, B, c.line, 7, 2.4)}
      <path d="M50 44 C44 26 46 12 53 12 C58 12 58 28 57 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M70 44 C76 26 74 12 67 12 C62 12 62 28 63 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M51 42 C47 28 49 18 53 18 Q55 30 55 44 Z" fill="${B}"/>
      <path d="M69 42 C73 28 71 18 67 18 Q65 30 65 44 Z" fill="${B}"/>
    </g>
    <g class="breathe">
      <path d="M60 110 C40 110 33 96 35 82 C36 72 40 66 46 62 C40 56 39 46 44 40 C50 33 54 33 60 33 C66 33 70 33 76 40 C81 46 80 56 74 62 C80 66 84 72 85 82 C87 96 80 110 60 110 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="17" ry="18" fill="${B}"/>
      <path d="M54 34 Q50 22 51 15 M51 20 Q47 17 45 12 M52 18 Q49 15 50 9" fill="none" stroke="${HORN}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M66 34 Q70 22 69 15 M69 20 Q73 17 75 12 M68 18 Q71 15 70 9" fill="none" stroke="${HORN}" stroke-width="2.6" stroke-linecap="round"/>
      <ellipse cx="60" cy="52" rx="15" ry="13" fill="${B}"/>
      <path d="M60 54 l-3.5 3.5 h7 Z" fill="${c.shade}"/>
      <path d="M60 57 v3 M60 60 q-4 3 -8 2 M60 60 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${ceye(51, 47, 4)}${ceye(69, 47, 4)}
      <path d="M34 66 h-10 M35 70 h-11 M86 66 h10 M85 70 h11" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>
    </g>`; },

  // ── Loch Ness Monster — long-neck plesiosaur, smooth hump, paddle flippers, small friendly head (float) ──
  lochnessmonster: (c) => { const B = belly(c); return `
    ${floorShadow(56, 110, 30)}
    <g class="tail-wag">
      <path d="M22 84 Q12 74 6 80 Q4 86 10 88 Q18 90 22 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M40 90 Q34 102 42 104 Q48 100 46 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M64 90 Q58 102 66 104 Q72 100 70 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M18 84 Q20 64 46 64 Q72 64 76 82 Q76 92 58 92 Q30 94 18 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M26 84 Q46 92 70 84 Q48 90 26 84 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      ${tube("M68 78 Q84 74 88 46", c.body, c.line, 12)}
      <path d="M78 44 Q78 32 90 32 Q102 32 104 42 Q104 48 98 50 Q86 52 80 48 Q77 48 78 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M84 30 Q83 22 88 22 M92 30 Q92 22 97 24" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="101" cy="43" rx="1.4" ry="1.1" fill="${INK}"/>
      <path d="M92 48 q6 2 10 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${ceye(88, 40, 3.6)}
    </g>`; },

  // ── Wendigo — gaunt antlered wraith, ribs showing, hollow glowing eyes, spindly clawed arms (front) ──
  wendigo: (c) => { const B = belly(c), D = deepen(c.body, 0.2); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      <path d="M50 30 Q42 16 44 7 M46 18 Q38 15 34 9 M46 14 Q40 10 40 3 M48 22 Q40 22 34 18" fill="none" stroke="${HORN}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M70 30 Q78 16 76 7 M74 18 Q82 15 86 9 M74 14 Q80 10 80 3 M72 22 Q80 22 86 18" fill="none" stroke="${HORN}" stroke-width="2.6" stroke-linecap="round"/>
      ${tube("M50 60 Q37 74 35 92", c.body, c.line, 4.5)}
      ${tube("M70 60 Q83 74 85 92", c.body, c.line, 4.5)}
      <path d="M33 90 l-2 6 m2 -6 l3 4 M87 90 l2 6 m-2 -6 l-3 4" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M52 44 C49 28 54 22 60 22 C66 22 71 28 68 44 C74 48 74 56 70 60 C78 64 80 76 78 88 L74 110 L66 110 L64 90 L56 90 L54 110 L46 110 L42 88 C40 76 42 64 50 60 C46 56 46 48 52 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 66 Q60 71 68 66 M50 74 Q60 79 70 74 M52 82 Q60 86 68 82" fill="none" stroke="${D}" stroke-width="1.8" stroke-linecap="round" opacity=".7"/>
      <ellipse cx="60" cy="38" rx="12" ry="13" fill="${B}"/>
      <path d="M54 52 q6 3 12 0 q-2 5 -6 5 q-4 0 -6 -5 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M55 53 l1.4 4 l1.4 -4 M62 53 l1.4 4 l1.4 -4" fill="none" stroke="${TOOTH}" stroke-width="1"/>
      <path d="M60 44 l-2.5 4 h5 Z" fill="${c.shade}"/>
      ${glow(53, 40, 3.4, GLOW)}${glow(67, 40, 3.4, GLOW)}
      <path d="M48 34 q5 -2 9 0 M63 34 q5 -2 9 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    </g>`; },

  // ── Jersey Devil — winged goat-horse fiend, ram horns, bat wings, forked tail, hooves, red eyes (float) ──
  jerseydevil: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      <path d="M52 60 Q40 68 28 64 Q33 73 29 82 Q40 78 51 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M68 60 Q80 68 92 64 Q87 73 91 82 Q80 78 69 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${tube("M60 82 Q66 104 58 112", c.body, c.line, 4)}
      <path d="M58 112 l-3 4 l4 -1 l1 4 l3 -5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M48 44 C48 30 54 24 60 24 C66 24 72 30 72 44 C74 50 74 56 70 60 C76 64 80 74 78 84 L74 100 L66 100 L64 84 L56 84 L54 100 L46 100 L42 84 C40 74 44 64 50 60 C46 56 46 50 48 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 30 Q44 20 38 18 Q45 26 47 36 Z M70 30 Q76 20 82 18 Q75 26 73 36 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="46" rx="9" ry="9" fill="${B}"/>
      <path d="M53 52 Q60 57 67 52 Q65 44 60 44 Q55 44 53 52 Z" fill="${c.shade}"/>
      <ellipse cx="57" cy="53" rx="1" ry="1.3" fill="${INK}"/><ellipse cx="63" cy="53" rx="1" ry="1.3" fill="${INK}"/>
      ${glow(55, 42, 3, RED)}${glow(65, 42, 3, RED)}
      <path d="M52 100 l3 4 M66 100 l3 4" stroke="${HOOF}" stroke-width="3.4" stroke-linecap="round"/>
    </g>`; },

  // ── Bunyip — plump shaggy swamp beast, downward tusks, big nose, flippers, whiskers (front) ──
  bunyip: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M28 78 Q12 84 14 98 Q24 100 34 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M92 78 Q108 84 106 98 Q96 100 86 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${pom(60, 78, 32, c.body, c.line, 15, 3.2)}
      <ellipse cx="60" cy="86" rx="22" ry="18" fill="${B}"/>
      <path d="M40 104 Q46 112 54 106 Q48 102 42 102 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M80 104 Q74 112 66 106 Q72 102 78 102 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="45" cy="52" rx="6" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="75" cy="52" rx="6" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="72" rx="13" ry="10" fill="${c.shade}"/>
      <path d="M54 74 l-2 12 q4 3 6 -1 Z M66 74 l2 12 q-4 3 -6 -1 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="6" ry="4.4" fill="${INK}"/>
      <ellipse cx="57.6" cy="64.6" rx="1.6" ry="1.2" fill="#fff" opacity=".85"/>
      ${ceye(50, 58, 4)}${ceye(70, 58, 4)}
      <path d="M40 66 h-12 M40 70 h-13 M80 66 h12 M80 70 h13" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".45"/>
    </g>`; },

  // ── Kelpie — Scottish water horse, dripping wet mane, fishy fin-tail, webbed hooves, water beads (profile) ──
  kelpie: (c) => { const B = belly(c); return `
    ${floorShadow(56, 108, 28)}
    <g class="tail-wag">
      <path d="M30 70 Q10 62 4 76 Q14 74 12 84 Q22 82 28 78 Q34 88 40 82 Q34 74 34 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M8 74 q6 2 6 8 M18 76 q4 2 4 7" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".55"/>
    </g>
    <g class="breathe">
      <path d="M28 74 C28 60 44 56 62 57 C74 58 80 62 80 70 C80 82 70 84 58 84 C40 84 28 82 28 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 80 Q54 88 74 80 Q54 86 34 80 Z" fill="${B}"/>
      <rect x="36" y="80" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="62" y="80" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="46" y="82" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <rect x="70" y="82" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M35 100 q5 5 10 2 M45 100 q5 5 10 2 M61 100 q5 5 10 2 M69 100 q5 5 10 2" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${tube("M72 64 Q80 54 86 46", c.body, c.line, 13)}
      <path d="M80 46 Q78 36 88 33 Q97 33 101 40 L105 50 Q108 54 103 58 Q96 60 90 57 Q80 55 80 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M101 52 Q108 54 105 60 Q100 62 96 58 Z" fill="${c.shade}"/>
      <ellipse cx="102" cy="53" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M82 36 Q78 26 86 22 Q92 30 90 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 40 Q66 40 62 52 Q70 48 74 52 Q64 52 60 64 Q72 56 80 56 Q76 48 82 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M64 52 q-3 6 -1 10 M70 50 q-2 5 0 9" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".55"/>
      ${eye(93, 47, 3, INK)}
      <circle cx="52" cy="46" r="1.6" fill="${GLOW}"/><circle cx="46" cy="54" r="1.3" fill="${GLOW}"/>
    </g>`; },

  // ── Ogopogo — humped lake serpent, undulating coils, horned mane-fringed head, little fangs (float) ──
  ogopogo: (c) => { const B = belly(c); return `
    ${floorShadow(56, 110, 30)}
    <g class="breathe">
      <path d="M8 90 Q10 74 20 74 Q30 74 32 88 Q34 74 44 74 Q54 74 56 88 Q58 74 68 74 Q78 74 80 84 L82 92 Q46 96 8 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M14 90 Q46 94 78 88" fill="none" stroke="${B}" stroke-width="4" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      ${tube("M78 84 Q92 78 94 56", c.body, c.line, 11)}
      <path d="M84 54 Q84 42 96 42 Q108 42 108 52 Q108 60 100 62 L112 64 Q108 70 98 66 Q84 66 84 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M88 42 L86 30 L93 40 Z M98 42 L100 30 L102 42 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 50 Q76 48 72 52 M84 55 Q76 57 74 62" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M104 62 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      ${ceye(96, 52, 3.4)}
    </g>`; },

  // ── Sasquatch — round cuddly shaggy ape, hunched fluff-ball, big feet forward (front) ──
  sasquatch: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M40 62 Q28 64 26 78 Q25 90 31 96 Q38 100 42 92 Q39 82 44 74 Q41 66 48 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M80 62 Q92 64 94 78 Q95 90 89 96 Q82 100 78 92 Q81 82 76 74 Q79 66 72 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${pom(60, 80, 30, c.body, c.line, 14, 3.2)}
      ${pom(44, 106, 10, c.body, c.line, 7, 2.6)}${pom(76, 106, 10, c.body, c.line, 7, 2.6)}
      <ellipse cx="60" cy="82" rx="18" ry="16" fill="${B}"/>
      ${pom(60, 50, 20, c.body, c.line, 12, 3)}
      <ellipse cx="60" cy="54" rx="14" ry="12" fill="${B}"/>
      <path d="M49 46 q6 -3 11 0 M60 46 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <ellipse cx="60" cy="57" rx="4.6" ry="3.2" fill="${c.shade}"/>
      <path d="M52 63 q8 5 16 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${ceye(53, 51, 3.6)}${ceye(67, 51, 3.6)}
    </g>`; },

  // ── Owlman — Cornish owl-humanoid, big facial-disc eyes, ear tufts, feathered chest, talons (float) ──
  owlman: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M50 56 Q26 50 14 64 Q26 66 32 66 Q22 74 22 86 Q40 82 52 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M70 56 Q94 50 106 64 Q94 66 88 66 Q98 74 98 86 Q80 82 68 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M30 64 q6 4 12 4 M28 72 q8 4 14 2 M90 64 q-6 4 -12 4 M92 72 q-8 4 -14 2" fill="none" stroke="${c.shade}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M46 42 L44 26 L54 34 Q57 30 60 30 Q63 30 66 34 L76 26 L74 42 C80 48 82 62 80 76 C82 92 74 108 60 108 C46 108 38 92 40 76 C38 62 40 48 46 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 62 Q60 56 72 62 M46 74 Q60 68 74 74 M48 86 Q60 80 72 86" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
      <ellipse cx="60" cy="46" rx="17" ry="15" fill="${B}"/>
      <circle cx="52" cy="46" r="8" fill="#fff" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="68" cy="46" r="8" fill="#fff" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="52" cy="46" r="4.2" fill="${HORN}"/><circle cx="52" cy="46" r="2.4" fill="${INK}"/>
      <circle cx="68" cy="46" r="4.2" fill="${HORN}"/><circle cx="68" cy="46" r="2.4" fill="${INK}"/>
      <circle cx="50.5" cy="44.5" r="1.1" fill="#fff"/><circle cx="66.5" cy="44.5" r="1.1" fill="#fff"/>
      <path d="M60 52 l-3 4 h6 Z" fill="${HOOF}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M50 104 l-3 6 M56 106 l-1 5 M64 106 l1 5 M70 104 l3 6" stroke="${HOOF}" stroke-width="2.4" stroke-linecap="round"/>
    </g>`; },

  // ── Dover Demon — huge bulbous head, giant glowing oval eyes, spindly stick limbs, no mouth (front) ──
  doverdemon: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 20)}
    <g class="tail-wag">
      ${tube("M52 74 Q40 82 34 96", c.body, c.line, 3.5)}
      ${tube("M68 74 Q80 82 86 96", c.body, c.line, 3.5)}
    </g>
    <g class="breathe">
      <path d="M60 22 C40 22 32 38 34 52 C35 62 44 66 52 68 C48 74 48 84 52 92 L48 106 L56 106 L58 94 L62 94 L64 106 L72 106 L68 92 C72 84 72 74 68 68 C76 66 85 62 86 52 C88 38 80 22 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="46" rx="22" ry="18" fill="${B}"/>
      <ellipse cx="51" cy="45" rx="6" ry="8" fill="${HORN}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="69" cy="45" rx="6" ry="8" fill="${HORN}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="51" cy="46" rx="2.4" ry="3.4" fill="${INK}"/><ellipse cx="69" cy="46" rx="2.4" ry="3.4" fill="${INK}"/>
      <circle cx="49.4" cy="42.6" r="1.2" fill="#fff"/><circle cx="67.4" cy="42.6" r="1.2" fill="#fff"/>
    </g>`; },

  // ── Flatwoods Monster — hovering hooded figure, ace-of-spades cowl, glowing eyes, pleated robe (front) ──
  flatwoodsmonster: (c) => { const B = belly(c); return `
    ${floorShadow(60, 110, 24)}
    <g class="breathe">
      <path d="M40 104 Q38 66 52 58 Q60 54 68 58 Q82 66 80 104 Q60 110 40 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 64 Q60 60 68 64 L66 104 L54 104 Z" fill="${B}" opacity=".6"/>
      <path d="M48 104 v-30 M60 106 v-34 M72 104 v-30" stroke="${c.shade}" stroke-width="1.8" opacity=".55"/>
    </g>
    <g class="tail-wag">
      ${tube("M42 78 Q30 86 28 98", c.body, c.line, 4)}
      ${tube("M78 78 Q90 86 92 98", c.body, c.line, 4)}
      <path d="M26 96 l-3 6 l5 -2 l1 5 l3 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M94 96 l3 6 l-5 -2 l-1 5 l-3 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M60 10 C44 26 40 40 52 48 Q56 50 60 48 Q64 50 68 48 C80 40 76 26 60 10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M55 47 h10 l-2 9 h-6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="40" rx="11" ry="9" fill="${INK}"/>
      ${glow(55, 40, 3, GLOW)}${glow(65, 40, 3, GLOW)}
    </g>`; },

  // ── Thunderbird — colossal eagle, wide feathered wings, fierce brow, hooked beak, talons (float) ──
  thunderbird: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M48 52 Q22 40 8 50 Q18 54 26 56 Q12 60 8 72 Q26 70 40 62 Q28 68 24 80 Q44 74 52 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M72 52 Q98 40 112 50 Q102 54 94 56 Q108 60 112 72 Q94 70 80 62 Q92 68 96 80 Q76 74 68 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M46 44 C46 30 52 24 60 24 C68 24 74 30 74 44 C80 48 82 62 80 76 C82 92 74 108 60 108 C46 108 38 92 40 76 C38 62 40 48 46 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 66 Q60 60 70 66 M48 78 Q60 72 72 78 M50 90 Q60 84 70 90" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
      <ellipse cx="60" cy="42" rx="13" ry="12" fill="${B}"/>
      <path d="M44 36 q7 -4 13 -1 M63 35 q6 -3 13 1" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M53 47 Q60 44 67 47 Q65 55 60 58 Q62 62 58 63 Q56 58 55 55 Q53 51 53 47 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M55 50 q5 2 10 0" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
      ${glow(53, 42, 3.2, GLOW)}${glow(67, 42, 3.2, GLOW)}
      <path d="M50 104 l-4 6 M56 106 l-1 6 M64 106 l1 6 M70 104 l4 6" stroke="${HOOF}" stroke-width="2.6" stroke-linecap="round"/>
    </g>`; },

  // ── Yowie — Aussie bigfoot brute, pot-belly, wide stance, tusked underbite, ear tufts, heavy brow (front) ──
  yowie: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag">
      <path d="M32 58 Q14 64 16 82 Q18 94 28 92 Q26 80 38 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M88 58 Q106 64 104 82 Q102 94 92 92 Q94 80 82 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 112 C34 112 24 98 26 80 C27 66 34 58 42 54 C40 46 44 36 52 34 Q60 32 68 34 C76 36 80 46 78 54 C86 58 93 66 94 80 C96 98 86 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="22" ry="18" fill="${B}"/>
      <ellipse cx="42" cy="108" rx="9" ry="5.5" fill="${c.shade}"/><ellipse cx="78" cy="108" rx="9" ry="5.5" fill="${c.shade}"/>
      <path d="M38 44 l-8 -6 l3 9 Z M82 44 l8 -6 l-3 9 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="50" rx="18" ry="15" fill="${B}"/>
      <path d="M48 39 q7 2 11 1 M61 40 q4 -1 11 -1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M50 53 q10 6 20 0 q-2 6 -10 6 q-8 0 -10 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M54 59 l1.5 6 l2 -5 Z M66 59 l-1.5 6 l-2 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="49" rx="5" ry="3" fill="${c.shade}"/>
      <ellipse cx="57.8" cy="49" rx="1.1" ry="1.4" fill="${INK}"/><ellipse cx="62.2" cy="49" rx="1.1" ry="1.4" fill="${INK}"/>
      ${ceye(52, 43, 3.4)}${ceye(68, 43, 3.4)}
    </g>`; },

  // ── Mokele Mbembe — Congo sauropod, round body, four legs, long tail, long neck, tiny head (profile) ──
  mokelembembe: (c) => { const B = belly(c); return `
    ${floorShadow(56, 110, 32)}
    <g class="tail-wag">
      ${tube("M30 76 Q14 74 8 90", c.body, c.line, 9)}
      ${tube("M12 88 Q6 92 6 98", c.body, c.line, 5)}
    </g>
    <g class="breathe">
      <path d="M26 78 Q24 58 52 56 Q78 56 84 72 Q86 84 72 86 Q46 88 30 86 Q24 86 26 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M32 82 Q54 90 78 82 Q54 88 32 82 Z" fill="${B}"/>
      <rect x="34" y="82" width="9" height="24" rx="3.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="64" y="82" width="9" height="24" rx="3.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="46" y="84" width="9" height="22" rx="3.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <rect x="54" y="84" width="9" height="22" rx="3.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
    </g>
    <g class="head-tilt">
      ${tube("M74 68 Q88 58 92 40", c.body, c.line, 11)}
      <path d="M84 40 Q84 30 94 30 Q104 30 106 38 Q106 46 98 48 Q88 48 84 44 Q82 44 84 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="104" cy="38" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M96 45 q6 2 9 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${ceye(91, 37, 3.4)}
    </g>`; },

  // ── Ahool — Indonesian giant bat, leathery finger-strut wings, fuzzy body, bat ears, little fangs (float) ──
  ahool: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M50 54 Q28 40 12 48 Q22 52 26 58 Q14 58 10 68 Q24 70 32 66 Q22 72 20 84 Q40 78 52 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M26 54 L20 46 M32 60 L26 68 M40 64 L36 74" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M70 54 Q92 40 108 48 Q98 52 94 58 Q106 58 110 68 Q96 70 88 66 Q98 72 100 84 Q80 78 68 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M94 54 L100 46 M88 60 L94 68 M80 64 L84 74" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M46 42 L44 32 L54 40 Q57 36 60 36 Q63 36 66 40 L76 32 L74 42 C80 48 82 62 80 76 C82 90 74 100 60 100 C46 100 38 90 40 76 C38 62 40 48 46 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="74" rx="11" ry="16" fill="${B}"/>
      <ellipse cx="60" cy="50" rx="14" ry="12" fill="${B}"/>
      <path d="M60 54 l-3 4 h6 Z" fill="${INK}"/>
      <path d="M52 60 q8 5 16 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M55 60 l1.5 4 l1.5 -4 M62 60 l1.5 4 l1.5 -4" fill="none" stroke="${TOOTH}" stroke-width="1"/>
      ${ceye(52, 48, 3.6)}${ceye(68, 48, 3.6)}
    </g>`; },

  // ── Yeren — Chinese red-haired wildman, lean human build, spiky wild hair crest, grin, visible hands (front) ──
  yeren: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M40 58 Q24 70 26 88 L34 88 Q34 74 46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M80 58 Q96 70 94 88 L86 88 Q86 74 74 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="30" cy="90" r="5.5" fill="${B}" stroke="${c.line}" stroke-width="2.4"/><circle cx="90" cy="90" r="5.5" fill="${B}" stroke="${c.line}" stroke-width="2.4"/>
    </g>
    <g class="breathe">
      <path d="M60 112 C44 112 36 100 38 84 C39 72 46 62 48 56 Q60 60 72 56 C74 62 81 72 82 84 C84 100 76 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="15" ry="16" fill="${B}"/>
      <ellipse cx="50" cy="108" rx="7" ry="5" fill="${c.shade}"/><ellipse cx="70" cy="108" rx="7" ry="5" fill="${c.shade}"/>
      <path d="M44 40 L40 22 L48 34 L50 18 L56 32 L60 13 L64 32 L70 18 L72 34 L80 22 L76 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="50" rx="16" ry="15" fill="${B}"/>
      <path d="M49 44 q6 -3 10 0 M61 44 q6 -3 10 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M60 52 l-3 5 h6 Z" fill="${c.shade}"/>
      <path d="M50 60 q10 8 20 0 q-3 6 -10 6 q-7 0 -10 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M53 62 h14 M57 66 l1.5 3 M63 66 l-1.5 3" stroke="${TOOTH}" stroke-width="1.4" fill="none"/>
      ${ceye(52, 48, 3.6)}${ceye(68, 48, 3.6)}
    </g>`; },

  // ── Grootslang — South African elephant-serpent, coiled snake body, elephant head, trunk & tusks (profile) ──
  grootslang: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 32)}
    <g class="tail-wag">
      ${tube("M62 92 Q92 96 96 74 Q98 62 86 60", c.body, c.line, 12)}
      ${tube("M86 60 Q78 56 74 60", c.body, c.line, 7)}
    </g>
    <g class="breathe">
      ${tube("M68 58 Q40 58 34 84 Q30 100 58 100 Q84 100 84 80", c.body, c.line, 16)}
      <path d="M40 92 Q58 100 78 92" fill="none" stroke="${B}" stroke-width="5" stroke-linecap="round" opacity=".55"/>
    </g>
    <g class="head-tilt">
      <path d="M50 40 Q30 34 26 46 Q30 56 46 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M70 40 Q90 34 94 46 Q90 56 74 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M44 40 Q44 24 60 24 Q76 24 76 40 Q76 56 68 60 Q60 62 52 60 Q44 56 44 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${tube("M60 56 Q58 74 66 84 Q70 90 66 94", c.body, c.line, 8)}
      <path d="M50 34 Q48 26 54 24 Q56 30 55 36 Z M70 34 Q72 26 66 24 Q64 30 65 36 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 46 Q50 42 46 44 M68 46 Q70 42 74 44" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${ceye(53, 42, 3.4)}${ceye(67, 42, 3.4)}
    </g>`; },
};

export const ROSTER_CRYPTIDS = [
  { n: "Bigfoot",            e: "🦶", tier: 3, float: false },
  { n: "Chupacabra",         e: "🧛", tier: 3, float: false },
  { n: "Mothman",            e: "🦋", tier: 4, float: true },
  { n: "Jackalope",          e: "🐰", tier: 2, float: false },
  { n: "Loch Ness Monster",  e: "🦕", tier: 4, float: true },
  { n: "Wendigo",            e: "🦌", tier: 4, float: false },
  { n: "Jersey Devil",       e: "😈", tier: 4, float: true },
  { n: "Bunyip",             e: "🦭", tier: 3, float: false },
  { n: "Kelpie",             e: "🐴", tier: 3, float: false },
  { n: "Ogopogo",            e: "🐍", tier: 3, float: true },
  { n: "Sasquatch",          e: "🦍", tier: 3, float: false },
  { n: "Owlman",             e: "🦉", tier: 3, float: true },
  { n: "Dover Demon",        e: "👽", tier: 3, float: false },
  { n: "Flatwoods Monster",  e: "♠️", tier: 3, float: true },
  { n: "Thunderbird",        e: "🦅", tier: 4, float: true },
  { n: "Yowie",              e: "🐒", tier: 3, float: false },
  { n: "Mokele Mbembe",      e: "🦖", tier: 4, float: false },
  { n: "Ahool",              e: "🦇", tier: 3, float: true },
  { n: "Yeren",              e: "🧌", tier: 3, float: false },
  { n: "Grootslang",         e: "🐘", tier: 4, float: false },
];
