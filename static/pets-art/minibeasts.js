// pets-art/minibeasts.js — BESPOKE hand-drawn SVG art for the MINIBEASTS batch of NADO Pets (extra
// insects & arachnids, distinct from the bugs.js batch). Each entry: slug -> (c) => "<svg inner markup>"
// for <svg viewBox="0 0 120 120">. Coat: c.body (main), c.shade (darker accent/underside), c.line
// (outline). Fliers => float:true (frame drifts). viewBox 0 0 120 120, x,y kept in [8,112].
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// translucent gossamer wing fill (kept light so the c.line outline reads on any coat)
const WING = "#eaf6ff";
// a big glossy round eye that reads on ANY coat (white sclara + dark pupil + catchlight); blinks
const gEye = (x, y, r) => `<g class="blink"><circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${INK}" stroke-width="1.5"/><circle cx="${x}" cy="${y}" r="${(r * 0.52).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.32).toFixed(1)}" cy="${(y - r * 0.34).toFixed(1)}" r="${(r * 0.24).toFixed(1)}" fill="#fff"/></g>`;

export const ART_MINIBEASTS = {
  // Jumping Spider — compact fuzzy spider dominated by two enormous forward eyes, short bent legs
  jumpingspider: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.8" stroke-linecap="round"/>`;
    const left = [
      "M48 56 Q34 46 26 48 Q21 49 20 55",
      "M46 64 Q30 60 20 64 Q15 66 16 72",
      "M46 72 Q30 72 20 78 Q16 81 17 86",
      "M48 80 Q36 88 30 98 Q28 102 29 106",
    ].map(leg).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">
      ${pom(60, 88, 15, c.shade, c.line, 13, 2.4)}
      ${pom(60, 62, 20, c.body, c.line, 15, 2.6)}
      <path d="M44 60 Q60 52 76 60" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M52 76 q-2 5 -6 7 M68 76 q2 5 6 7" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      <circle cx="44" cy="48" r="2.2" fill="${E}"/><circle cx="76" cy="48" r="2.2" fill="${E}"/>
      <circle cx="55" cy="45" r="1.6" fill="${E}"/><circle cx="65" cy="45" r="1.6" fill="${E}"/>
      ${gEye(50, 60, 7)}${gEye(70, 60, 7)}
    </g>`;
  },

  // Wolf Spider — robust ground spider, long splayed legs, chevron dorsal stripe, forward eye pair
  wolfspider: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`;
    const left = [
      "M50 56 Q30 40 14 42 Q9 43 8 49",
      "M48 66 Q26 58 12 60 Q7 62 8 68",
      "M48 74 Q26 76 12 82 Q8 85 9 90",
      "M50 82 Q34 92 26 102 Q24 106 26 108",
    ].map(leg).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">
      <ellipse cx="60" cy="80" rx="23" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M60 66 L50 78 M60 66 L70 78 M60 78 L52 88 M60 78 L68 88" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".8"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="52" rx="15" ry="13" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M54 63 q-2 5 -6 7 M66 63 q2 5 6 7" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${eyes(53, 67, 50, 3.2, E)}
      <circle cx="48" cy="46" r="1.8" fill="${E}"/><circle cx="72" cy="46" r="1.8" fill="${E}"/>
      <circle cx="57" cy="44" r="1.5" fill="${E}"/><circle cx="63" cy="44" r="1.5" fill="${E}"/>
    </g>`;
  },

  // Black Widow — glossy bulbous round abdomen with a pale hourglass, tiny head, thin delicate legs
  blackwidow: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`;
    const left = [
      "M56 88 Q34 78 22 58 Q18 51 22 46",
      "M55 90 Q34 86 20 72 Q15 66 17 60",
      "M56 94 Q38 96 24 92 Q18 90 16 84",
      "M57 98 Q44 106 32 110 Q27 112 25 108",
    ].map(leg).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">
      <circle cx="60" cy="56" r="26" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="50" cy="46" rx="7" ry="5" fill="#fff" opacity=".18"/>
      <path d="M54 44 L66 44 L60 56 Z M54 68 L66 68 L60 56 Z" fill="${B}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="88" r="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      ${eyes(55, 65, 86, 2.4, E)}
      ${smile(60, 90, 2.4, E)}
    </g>`;
  },

  // Orb Weaver — spider centred on a radial web, big concentrically patterned abdomen, gripping legs
  orbweaver: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const web = `<g opacity=".5" stroke="${B}" stroke-width="1.3" fill="none" stroke-linecap="round">
      <path d="M60 60 L60 10 M60 60 L102 30 M60 60 L108 62 M60 60 L98 100 M60 60 L60 112 M60 60 L22 100 M60 60 L12 62 M60 60 L18 30"/>
      <path d="M60 26 L84 42 L92 62 L82 88 L60 96 L38 88 L28 62 L36 42 Z"/>
      <path d="M60 40 L74 50 L79 62 L73 78 L60 84 L47 78 L41 62 L46 50 Z"/>
    </g>`;
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>`;
    const left = [
      "M50 56 Q34 46 26 40 Q22 37 20 40",
      "M48 62 Q30 58 20 56 Q16 55 15 58",
      "M48 68 Q30 70 20 74 Q16 76 16 80",
      "M50 74 Q36 84 30 92 Q28 96 30 98",
    ].map(leg).join("");
    return `
    ${web}
    ${left}${mirror(left)}
    <g class="breathe">
      <circle cx="60" cy="58" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="60" cy="58" r="12" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".7"/>
      <path d="M46 52 Q60 44 74 52" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      <path d="M50 66 L54 60 M60 68 L60 60 M70 66 L66 60" stroke="${c.shade}" stroke-width="1.8" opacity=".7" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="82" r="10" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      ${eyes(55, 65, 80, 2.4, E)}
      ${smile(60, 84, 2.2, E)}
    </g>`;
  },

  // Harvestman — daddy longlegs: one tiny round body with a two-eyed turret, eight enormous kneed legs
  harvestman: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>`;
    const left = [
      "M54 60 Q30 28 20 24 Q26 50 10 60",
      "M54 63 Q22 44 10 46 Q16 72 6 90",
      "M55 67 Q24 66 12 72 Q18 92 16 108",
      "M56 71 Q34 80 28 92 Q30 102 34 110",
    ].map(leg).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">
      <ellipse cx="60" cy="64" rx="11" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="62" rx="5" ry="3.4" fill="${c.shade}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="57" r="4.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="57.4" cy="56" r="1.6" fill="${E}"/><circle cx="62.6" cy="56" r="1.6" fill="${E}"/>
      ${smile(60, 66, 2, E)}
    </g>`;
  },

  // Weevil — plump beetle with a long down-curved snout (rostrum) and elbowed antennae on the snout
  weevil: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`;
    return `
    ${leg("M38 84 q-5 11 -9 16")}${leg("M50 88 q-1 12 -2 17")}${leg("M62 88 q3 11 6 15")}${leg("M70 82 q7 9 12 12")}
    <g class="breathe">
      <ellipse cx="50" cy="72" rx="26" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M50 54 L50 92" stroke="${c.line}" stroke-width="2" opacity=".55"/>
      <path d="M34 64 Q30 78 36 90 M66 64 Q70 78 64 90" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      <ellipse cx="50" cy="66" rx="18" ry="7" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="74" cy="64" r="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M82 62 Q98 66 100 82 Q100 88 96 90" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M82 62 Q98 66 100 82 Q100 88 96 90" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
      <path d="M90 74 q10 -6 16 -12 M90 74 q-3 -8 -7 -12" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(72, 61, 3, E)}
    </g>`;
  },

  // Cicada — stout body with big broad transparent veined wings held roof-like, wide-set eyes (float)
  cicada: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const wing = `<path d="M56 58 Q30 40 14 54 Q6 64 22 74 Q44 80 58 68 Z" fill="${WING}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>
      <path d="M50 60 Q32 56 20 62 M52 66 Q36 66 26 72" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`;
    const wing2 = `<path d="M58 64 Q34 66 20 82 Q14 90 30 92 Q50 90 60 76 Z" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".82"/>
      <path d="M52 70 Q36 74 26 84" fill="none" stroke="${c.line}" stroke-width="1" opacity=".45"/>`;
    return `
    <g class="tail-wag">${wing}${wing2}</g>
    <g class="breathe">
      <path d="M52 52 Q66 48 80 52 Q94 56 96 66 Q94 78 78 82 Q60 84 52 76 Q46 64 52 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 54 Q72 52 84 56" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      <path d="M62 78 Q74 82 84 78 Q74 84 62 78 Z" fill="${B}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M84 56 Q98 56 98 66 Q98 76 84 76 Q78 66 84 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${gEye(92, 60, 5)}${gEye(92, 72, 5)}
      ${smile(90, 68, 2.2, E)}
    </g>`;
  },

  // Termite — soft pale ant-relative: round pale head with tiny mandibles + straight antennae, plump gaster
  termite: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`;
    return `
    ${leg("M40 78 q-6 9 -12 12")}${leg("M50 82 q-3 10 -6 15")}${leg("M60 82 q3 10 6 15")}
    ${leg("M46 80 q-10 6 -18 6")}${leg("M62 78 q8 8 14 10")}
    <g class="breathe">
      <ellipse cx="40" cy="70" rx="22" ry="16" fill="${B}" stroke="${c.line}" stroke-width="2.4"/>
      ${[30, 40, 50].map((x) => `<path d="M${x} 56 Q${x} 70 ${x} 84" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>`).join("")}
      <ellipse cx="64" cy="66" rx="10" ry="9" fill="${tint(c.body, 0.4)}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="head-tilt">
      <circle cx="82" cy="64" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M93 60 Q100 58 104 60 M93 68 Q100 70 104 70" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M88 54 Q98 50 104 52 M88 74 Q98 78 104 76" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(78, 88, 62, 2.4, E)}
      ${smile(83, 67, 2.4, E)}
    </g>`;
  },

  // Earwig — long flat body ending in a pair of curved rear forceps (pincers), feelers up front
  earwig: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`;
    const pin = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>`;
    return `
    ${leg("M48 78 q-5 9 -10 13")}${leg("M60 80 q-1 10 -2 15")}${leg("M72 78 q4 9 9 12")}
    ${leg("M52 79 q-8 8 -14 11")}${leg("M66 79 q6 9 12 11")}
    <g class="tail-wag">
      ${pin("M32 62 Q16 54 12 44 Q11 40 16 42")}
      ${pin("M32 70 Q16 78 12 88 Q11 92 16 90")}
    </g>
    <g class="breathe">
      <path d="M30 66 Q30 56 46 55 Q72 54 84 60 Q88 66 84 72 Q72 78 46 77 Q30 76 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[42, 52, 62, 72].map((x) => `<path d="M${x} 57 Q${x - 2} 66 ${x} 75" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".55"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="88" cy="65" r="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M96 58 Q106 52 110 44 M97 64 Q108 62 112 58" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(84, 93, 63, 2.4, E)}
      ${smile(89, 68, 2.2, E)}
    </g>`;
  },

  // Cockroach — flat glossy oval, pronotum shield over a small head, two very long sweeping antennae
  cockroach: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`;
    return `
    ${leg("M42 84 q-10 8 -22 8")}${leg("M46 90 q-8 12 -18 18")}${leg("M52 92 q-3 14 -6 20")}
    ${leg("M78 84 q10 8 22 8")}${leg("M74 90 q8 12 18 18")}${leg("M68 92 q3 14 6 20")}
    <g class="head-tilt">
      <path d="M52 42 Q60 30 68 42 Q72 50 68 56 Q60 60 52 56 Q48 50 52 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 44 Q30 26 14 12 M68 44 Q90 26 106 12" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eyes(55, 65, 46, 2.4, E)}
      ${smile(60, 50, 2.2, E)}
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="76" rx="31" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M40 58 Q60 50 80 58 Q82 66 60 66 Q38 66 40 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="53" cy="57" rx="3" ry="3.8" fill="${deepen(c.body, .5)}"/><ellipse cx="67" cy="57" rx="3" ry="3.8" fill="${deepen(c.body, .5)}"/>
      <path d="M60 66 L60 94" stroke="${c.line}" stroke-width="1.8" opacity=".55"/>
      <path d="M46 68 Q42 82 50 92 M74 68 Q78 82 70 92" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".5"/>
    </g>`;
  },

  // Water Strider — slim body on six very long splayed legs resting on water, with surface dimples
  waterstrider: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    const dimp = (x) => `<ellipse cx="${x}" cy="96" rx="6" ry="2" fill="${WING}" opacity=".5"/>`;
    return `
    <path d="M8 92 Q60 88 112 92" fill="none" stroke="${WING}" stroke-width="2" opacity=".45"/>
    ${dimp(16)}${dimp(34)}${dimp(86)}${dimp(104)}
    ${leg("M50 60 Q34 62 20 84 Q18 90 16 94")}${leg("M52 58 Q40 44 30 30 Q28 26 26 28")}${leg("M56 64 Q44 78 34 94 Q33 97 32 96")}
    ${leg("M70 60 Q86 62 100 84 Q102 90 104 94")}${leg("M68 58 Q80 44 90 30 Q92 26 94 28")}${leg("M64 64 Q76 78 86 94 Q87 97 88 96")}
    <g class="breathe">
      <ellipse cx="60" cy="60" rx="17" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="58" rx="9" ry="3" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="50" r="7" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M55 44 q-4 -6 -8 -8 M65 44 q4 -6 8 -8" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eyes(56, 64, 49, 2.2, E)}
      ${smile(60, 52, 2, E)}
    </g>`;
  },

  // Diving Beetle — streamlined aquatic dome with fringed oar hind legs and a couple of rising bubbles
  divingbeetle: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`;
    return `
    <circle cx="30" cy="34" r="4" fill="${WING}" stroke="${c.line}" stroke-width="1.2" opacity=".7"/>
    <circle cx="90" cy="28" r="3" fill="${WING}" stroke="${c.line}" stroke-width="1.2" opacity=".7"/>
    ${leg("M46 66 q-14 -4 -22 -10")}${leg("M44 74 q-16 2 -24 2")}${leg("M74 66 q14 -4 22 -10")}${leg("M76 74 q16 2 24 2")}
    <path d="M46 82 Q34 92 22 98" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    ${[[32, 92], [28, 95], [24, 98]].map(([x, y]) => `<path d="M${x} ${y} l-4 3" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>`).join("")}
    <path d="M74 82 Q86 92 98 98" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    ${[[88, 92], [92, 95], [96, 98]].map(([x, y]) => `<path d="M${x} ${y} l4 3" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>`).join("")}
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="27" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M60 48 L60 94" stroke="${c.line}" stroke-width="2" opacity=".5"/>
      <path d="M40 56 Q34 70 42 88 M80 56 Q86 70 78 88" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      <path d="M44 54 Q60 60 76 54" fill="none" stroke="${B}" stroke-width="3" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M50 50 a10 8 0 0 1 20 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M54 44 q-4 -6 -9 -8 M66 44 q4 -6 9 -8" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eyes(55, 65, 46, 2.4, E)}
    </g>`;
  },

  // Dung Beetle — beetle braced head-down against a big textured dung ball it is rolling
  dungbeetle: (c) => {
    const E = eyeInk(c);
    const D = deepen(c.body, 0.28);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">
      <circle cx="34" cy="76" r="24" fill="${D}" stroke="${c.line}" stroke-width="2.6"/>
      ${[[26, 66], [42, 70], [30, 84], [46, 82], [36, 76]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3" fill="${c.line}" opacity=".35"/>`).join("")}
      <circle cx="27" cy="68" r="6" fill="#fff" opacity=".12"/>
    </g>
    ${leg("M74 86 q-6 10 -12 16")}${leg("M84 88 q0 12 2 18")}
    ${leg("M66 66 q-14 -2 -22 -2")}${leg("M70 60 q-14 -8 -24 -12")}
    <g class="breathe">
      <ellipse cx="82" cy="76" rx="22" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M82 58 L82 94" stroke="${c.line}" stroke-width="2" opacity=".5"/>
      <path d="M66 62 Q82 54 98 62 Q98 72 82 72 Q66 72 66 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M60 62 Q52 66 54 74 Q58 80 66 78 Q70 72 66 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 64 q-6 -2 -9 1 M55 72 q-6 2 -8 5" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(63, 69, 2.6, E)}
    </g>`;
  },

  // Leaf Insect — flat leaf-shaped body with a midrib and lateral veins, leafy legs, tiny head at the tip
  leafinsect: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>`;
    return `
    ${leg("M46 60 Q30 54 22 44")}${leg("M46 76 Q28 76 18 84")}${leg("M48 90 Q36 98 30 106")}
    ${leg("M74 60 Q90 54 98 44")}${leg("M74 76 Q92 76 102 84")}${leg("M72 90 Q84 98 90 106")}
    <g class="breathe">
      <path d="M60 26 Q84 44 82 78 Q78 100 60 108 Q42 100 38 78 Q36 44 60 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 34 L60 100" stroke="${c.line}" stroke-width="2" opacity=".6"/>
      ${[46, 58, 70, 82].map((y) => `<path d="M60 ${y} Q50 ${y + 4} 44 ${y + 10} M60 ${y} Q70 ${y + 4} 76 ${y + 10}" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".55"/>`).join("")}
      <path d="M52 40 Q60 34 68 40 Q64 50 60 50 Q56 50 52 40 Z" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="30" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 24 q-4 -7 -9 -9 M65 24 q4 -7 9 -9" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eyes(56, 64, 29, 2.2, E)}
      ${smile(60, 33, 2, E)}
    </g>`;
  },

  // Walking Stick — extremely thin knobbly twig body held upright with long thin twiggy legs
  walkingstick: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>`;
    return `
    ${leg("M50 62 Q36 54 30 40 Q28 34 30 30")}${leg("M54 70 Q40 74 28 74 Q22 74 20 72")}${leg("M58 78 Q48 90 42 102 Q40 106 42 108")}
    ${leg("M64 58 Q78 50 86 40 Q90 36 92 38")}${leg("M66 66 Q80 68 92 66 Q98 66 100 64")}${leg("M62 74 Q72 88 78 100 Q80 104 78 106")}
    <g class="breathe">
      <path d="M58 34 Q66 30 68 40 Q70 54 66 70 Q63 86 58 96 Q54 88 55 72 Q56 54 54 42 Q53 34 58 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[46, 60, 74].map((y) => `<path d="M56 ${y} q4 1 7 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".55"/>`).join("")}
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="34" rx="8" ry="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 27 Q50 14 44 8 M64 27 Q70 14 76 8" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(56, 64, 33, 2.2, E)}
      ${smile(60, 37, 2, E)}
    </g>`;
  },

  // Assassin Bug — narrow abdomen, a slim pronotum neck, small head with a short curved stabbing beak
  assassinbug: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`;
    return `
    ${leg("M50 70 Q34 64 24 50 Q22 46 24 44")}${leg("M50 78 Q34 78 22 78 Q18 78 16 76")}${leg("M52 86 Q42 98 36 108")}
    ${leg("M70 70 Q86 64 96 50 Q98 46 96 44")}${leg("M70 78 Q86 78 98 78 Q102 78 104 76")}${leg("M68 86 Q78 98 84 108")}
    <g class="breathe">
      <path d="M60 96 Q44 92 42 76 Q42 64 52 60 Q60 58 68 60 Q78 64 78 76 Q76 92 60 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 62 L60 92" stroke="${c.line}" stroke-width="1.6" opacity=".45"/>
      <path d="M44 74 Q42 84 50 92 M76 74 Q78 84 70 92" fill="none" stroke="${B}" stroke-width="2.4" opacity=".45" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M56 58 Q54 50 60 48 Q66 50 64 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="42" rx="9" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 36 Q50 24 44 16 M64 36 Q70 24 76 16" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M58 48 Q54 56 58 64 Q62 58 60 50" fill="none" stroke="${c.line}" stroke-width="3.2" stroke-linecap="round"/>
      ${eyes(56, 64, 41, 2.4, E)}
    </g>`;
  },

  // Aphid — tiny round pear-soft body with a pair of upright rear cornicles, stubby legs, big eyes
  aphid: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    return `
    ${leg("M50 78 q-8 8 -12 16")}${leg("M58 82 q-3 10 -4 18")}${leg("M52 76 q-12 4 -20 4")}
    ${leg("M70 78 q8 8 12 16")}${leg("M66 82 q3 10 4 18")}${leg("M72 74 q12 2 20 0")}
    <g class="tail-wag">
      <path d="M50 52 Q46 40 48 34" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M50 52 Q46 40 48 34" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>
      <path d="M70 52 Q74 40 72 34" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M70 52 Q74 40 72 34" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M60 44 Q84 46 84 70 Q84 88 60 90 Q36 88 36 70 Q36 46 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="72" rx="16" ry="12" fill="${B}" opacity=".55"/>
    </g>
    <g class="head-tilt">
      <path d="M54 48 q-6 -8 -12 -12 M66 48 q6 -8 12 -12" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eyes(53, 67, 60, 3, E)}
      ${smile(60, 68, 2.6, E)}
    </g>`;
  },

  // Springtail — tiny round plump hexapod with a forked spring (furcula) tucked under its belly
  springtail: (c) => {
    const E = eyeInk(c);
    const B = belly(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    return `
    ${leg("M48 76 q-6 8 -10 14")}${leg("M56 80 q-2 9 -3 16")}
    ${leg("M72 76 q6 8 10 14")}${leg("M64 80 q2 9 3 16")}
    <g class="tail-wag">
      <path d="M50 82 Q42 96 30 96 Q22 96 20 90" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M50 82 Q42 96 30 96 Q22 96 20 90" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
      <path d="M56 84 Q50 100 38 102 Q30 102 28 96" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M56 84 Q50 100 38 102 Q30 102 28 96" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="62" cy="64" rx="22" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="62" cy="68" rx="13" ry="9" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M74 52 q6 -6 12 -8 M76 60 q8 -2 14 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(66, 78, 60, 2.8, E)}
      ${smile(72, 66, 2.4, E)}
    </g>`;
  },

  // Pill Bug — armoured roly-poly: an arched dome of overlapping plates, little legs peeking underneath
  pillbug: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    return `
    ${[34, 44, 54, 64, 74].map((x) => leg(`M${x} 88 q-1 6 -3 9`)).join("")}
    <g class="breathe">
      <path d="M20 88 Q18 50 60 48 Q102 50 100 88 Q100 92 94 92 L26 92 Q20 92 20 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[36, 50, 64, 78].map((x) => `<path d="M${x} 92 Q${x - 6} 66 ${x + 2} 50" fill="none" stroke="${c.line}" stroke-width="2" opacity=".55"/>`).join("")}
      <path d="M26 74 Q60 66 96 74" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M84 62 Q98 60 100 72 Q100 82 88 82 Q82 74 84 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M96 60 q8 -4 12 -10 M98 66 q9 -2 13 -4" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(86, 95, 70, 2.4, E)}
      ${smile(90, 75, 2.2, E)}
    </g>`;
  },

  // Mayfly — slender body, tall upright triangular gossamer wings, three very long trailing tail filaments (float)
  mayfly: (c) => {
    const E = eyeInk(c);
    const wing = `<path d="M56 58 Q40 22 30 24 Q24 26 30 46 Q40 62 56 62 Z" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
      <path d="M50 58 Q40 36 34 30 M52 60 Q44 44 40 34" fill="none" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>`;
    const wing2 = `<path d="M62 58 Q78 22 88 24 Q94 26 88 46 Q78 62 62 62 Z" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
      <path d="M68 58 Q78 36 84 30 M66 60 Q74 44 78 34" fill="none" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>`;
    return `
    <g class="tail-wag">
      <path d="M44 70 Q26 84 12 100 M46 72 Q30 90 20 108 M48 71 Q34 88 26 106" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">${wing}${wing2}</g>
    <g class="breathe">
      <path d="M44 70 Q56 62 74 64 Q86 66 88 70 Q86 76 74 76 Q56 78 44 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 68 Q66 66 82 70" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <circle cx="86" cy="68" r="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M92 62 q7 -4 10 -9 M93 66 q8 -1 12 -2" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M80 60 Q74 52 70 46 M78 62 Q72 56 66 54" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${gEye(88, 66, 5)}
    </g>`;
  },
};

export const ROSTER_MINIBEASTS = [
  { n: "Jumping Spider", e: "🕷️", tier: 2, float: false },
  { n: "Wolf Spider",    e: "🕷️", tier: 2, float: false },
  { n: "Black Widow",    e: "🕷️", tier: 3, float: false },
  { n: "Orb Weaver",     e: "🕸️", tier: 2, float: false },
  { n: "Harvestman",     e: "🕷️", tier: 1, float: false },
  { n: "Weevil",         e: "🪲", tier: 1, float: false },
  { n: "Cicada",         e: "🦗", tier: 2, float: true },
  { n: "Termite",        e: "🐜", tier: 1, float: false },
  { n: "Earwig",         e: "🦗", tier: 1, float: false },
  { n: "Cockroach",      e: "🪳", tier: 1, float: false },
  { n: "Water Strider",  e: "🦟", tier: 1, float: false },
  { n: "Diving Beetle",  e: "🪲", tier: 1, float: false },
  { n: "Dung Beetle",    e: "🪲", tier: 2, float: false },
  { n: "Leaf Insect",    e: "🍃", tier: 2, float: false },
  { n: "Walking Stick",  e: "🌿", tier: 2, float: false },
  { n: "Assassin Bug",   e: "🐛", tier: 2, float: false },
  { n: "Aphid",          e: "🐛", tier: 1, float: false },
  { n: "Springtail",     e: "🐛", tier: 1, float: false },
  { n: "Pill Bug",       e: "🐛", tier: 1, float: false },
  { n: "Mayfly",         e: "🦟", tier: 1, float: true },
];
