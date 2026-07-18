// pets-art/bugs.js — BESPOKE hand-drawn SVG art for the BUGS & ARACHNIDS batch of the NADO Pets roster.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (darker accent/underside/spots), c.line (outline stroke). Winged
// fliers => float:true (frame drifts). Helpers from ../pets-draw.js. viewBox 0 0 120 120, x,y in [8,112].
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// translucent gossamer wing fill (kept light so the c.line outline reads on any coat)
const WING = "#eef5ff";

export const ART_BUGS = {
  // Honeybee — plump horizontal body, dark banded abdomen (stinger tip), fuzzy thorax, two flutter wings
  honeybee: (c) => {
    const E = eyeInk(c);
    return `
    ${[34, 50, 64].map((x) => `<path d="M${x} 84 q-3 9 -7 13" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`).join("")}
    <g class="tail-wag">
      <ellipse cx="48" cy="40" rx="18" ry="10" transform="rotate(-22 48 40)" fill="${WING}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>
      <ellipse cx="70" cy="40" rx="14" ry="8" transform="rotate(-6 70 40)" fill="${WING}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M18 62 L9 66 L18 70 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="50" cy="66" rx="32" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[[40, 19], [30, 15], [21, 8]].map(([x, ry]) => `<ellipse cx="${x}" cy="66" rx="4.6" ry="${ry}" fill="${INK}"/>`).join("")}
      <ellipse cx="66" cy="65" rx="12" ry="16" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="head-tilt">
      <circle cx="87" cy="62" r="13" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M93 50 q7 -6 10 -13 M97 55 q9 -3 13 -6" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="103" cy="36" r="2.2" fill="${INK}"/><circle cx="110" cy="48" r="2.2" fill="${INK}"/>
      ${eyes(83, 92, 60, 2.8, E)}
      ${smile(87, 67, 3, E)}
    </g>`;
  },

  // Bumblebee — big round fuzzy ball, horizontal stripe bands, stubby wings, sweet upturned face
  bumblebee: (c) => {
    const E = eyeInk(c);
    const wing = `<ellipse cx="40" cy="42" rx="16" ry="10" transform="rotate(-28 40 42)" fill="${WING}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>`;
    return `
    ${[42, 60, 78].map((x) => `<path d="M${x} 94 q-2 8 -6 11" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`).join("")}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      ${pom(60, 72, 30, c.body, c.line, 15, 2.4)}
      <circle cx="60" cy="72" r="25.5" fill="${c.body}"/>
      ${[[56, 21], [70, 24], [83, 16]].map(([y, rx]) => `<ellipse cx="60" cy="${y}" rx="${rx}" ry="4.6" fill="${INK}"/>`).join("")}
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="44" r="13" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M53 34 q-4 -8 -3 -14 M67 34 q4 -8 3 -14" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="49" cy="19" r="2.2" fill="${INK}"/><circle cx="71" cy="19" r="2.2" fill="${INK}"/>
      ${eyes(54, 66, 44, 3, E)}
      ${smile(60, 49, 3, E)}
    </g>`;
  },

  // Ladybug — domed red shell, black seam down the middle, symmetric spots, dark head, dotty antennae
  ladybug: (c) => {
    return `
    ${[[40, 54], [36, 68], [40, 84]].flatMap(([x, y]) => [
      `<path d="M${x} ${y} q-14 1 -22 6" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`,
      `<path d="M${120 - x} ${y} q14 1 22 6" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`,
    ]).join("")}
    <g class="breathe">
      <circle cx="60" cy="68" r="31" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 38 L60 98" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      ${[[45, 56], [75, 56], [43, 76], [77, 76], [56, 90], [64, 90]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5.2" fill="${INK}"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M42 44 a18 12 0 0 1 36 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 34 q-4 -8 -9 -11 M70 34 q4 -8 9 -11" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="40" cy="21" r="2.4" fill="${INK}"/><circle cx="80" cy="21" r="2.4" fill="${INK}"/>
      <circle cx="52" cy="40" r="3.4" fill="#fff" stroke="${c.line}" stroke-width="1.2"/><circle cx="52.6" cy="40.6" r="1.6" fill="${INK}"/>
      <circle cx="68" cy="40" r="3.4" fill="#fff" stroke="${c.line}" stroke-width="1.2"/><circle cx="68.6" cy="40.6" r="1.6" fill="${INK}"/>
    </g>`;
  },

  // Butterfly — slim body, four big patterned wings with eye-spots and dotted edges, clubbed antennae
  butterfly: (c) => {
    const E = eyeInk(c);
    const upper = `<path d="M58 52 Q24 28 13 50 Q9 70 38 74 Q54 70 58 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="26" cy="52" r="6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M15 62 q10 6 22 6" fill="none" stroke="${c.shade}" stroke-width="1.6"/>`;
    const lower = `<path d="M58 66 Q32 72 25 94 Q37 104 52 92 Q58 80 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="38" cy="86" r="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="1.3"/>`;
    return `
    <g class="tail-wag">${upper}${lower}${mirror(upper)}${mirror(lower)}</g>
    <g class="head-tilt">
      <path d="M60 28 q-8 -8 -15 -16 M60 28 q8 -8 15 -16" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="45" cy="12" r="2.6" fill="${INK}"/><circle cx="75" cy="12" r="2.6" fill="${INK}"/>
      <path d="M60 26 q-7 4 -7 30 q0 20 7 26 q7 -6 7 -26 q0 -26 -7 -30 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(55, 65, 30, 2.4, E)}
    </g>`;
  },

  // Monarch Butterfly — orange wings webbed with black veins and a white-dotted dark border
  monarchbutterfly: (c) => {
    const E = eyeInk(c);
    const border = (pts) => pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.7" fill="#fff"/>`).join("");
    const upper = `<path d="M58 52 Q24 26 12 50 Q8 72 39 76 Q55 71 58 60 Z" fill="${c.body}" stroke="${INK}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M15 47 Q10 65 34 74 M12 56 Q14 68 30 74 M18 42 Q22 60 42 68" fill="none" stroke="${INK}" stroke-width="1.6"/>
      <path d="M13 44 Q6 52 9 66 Q18 76 40 76 L40 76" fill="none" stroke="${INK}" stroke-width="4"/>
      ${border([[13, 48], [11, 56], [12, 64], [20, 72], [30, 75]])}`;
    const lower = `<path d="M58 66 Q34 72 27 92 Q39 103 53 92 Q58 80 58 72 Z" fill="${c.body}" stroke="${INK}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 72 Q38 82 34 94 M54 74 Q46 84 44 96" fill="none" stroke="${INK}" stroke-width="1.6"/>
      <path d="M27 90 Q34 100 52 92" fill="none" stroke="${INK}" stroke-width="4"/>
      ${border([[33, 92], [40, 96], [48, 95]])}`;
    return `
    <g class="tail-wag">${upper}${lower}${mirror(upper)}${mirror(lower)}</g>
    <g class="head-tilt">
      <path d="M60 28 q-8 -8 -15 -16 M60 28 q8 -8 15 -16" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="45" cy="12" r="2.6" fill="${INK}"/><circle cx="75" cy="12" r="2.6" fill="${INK}"/>
      <path d="M60 26 q-7 4 -7 30 q0 20 7 26 q7 -6 7 -26 q0 -26 -7 -30 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(55, 65, 30, 2.4, E)}
    </g>`;
  },

  // Moth — fat fuzzy body, broad drab wings held wide with concentric eyespots, feathery comb antennae
  moth: (c) => {
    const E = eyeInk(c);
    const wing = `<path d="M56 54 Q22 40 12 60 Q10 82 40 84 Q54 78 56 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="30" cy="64" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <circle cx="30" cy="64" r="3.4" fill="${INK}"/>
      <path d="M14 74 q14 8 30 6" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".8"/>`;
    return `
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">${pom(60, 68, 15, c.shade, c.line, 12, 2.2)}</g>
    <g class="head-tilt">
      ${pom(60, 46, 10, c.shade, c.line, 9, 2.2)}
      <path d="M53 40 q-8 -3 -14 -10 M53 40 q-9 1 -15 -3 M67 40 q8 -3 14 -10 M67 40 q9 1 15 -3" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(55, 65, 45, 2.6, E)}
      ${smile(60, 49, 2.6, E)}
    </g>`;
  },

  // Ant — three segments (round head, thorax, big teardrop gaster) on a pinched waist, six legs, elbowed feelers
  ant: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>`;
    return `
    ${leg("M50 66 Q40 74 34 70 Q30 78 24 82")}${leg("M52 70 Q44 82 36 84 Q32 92 26 96")}${leg("M55 72 Q52 86 46 90 Q44 98 40 102")}
    ${leg("M68 64 Q80 62 84 56")}${leg("M69 68 Q82 70 88 68")}${leg("M68 72 Q80 80 84 88")}
    <g class="breathe">
      <path d="M30 66 Q18 62 14 70 Q18 82 30 80 Q42 78 42 72 Q42 66 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="52" cy="68" rx="12" ry="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
    </g>
    <g class="head-tilt">
      <circle cx="76" cy="62" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M82 51 q4 -8 2 -14 M87 55 q7 -6 8 -13" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="84" cy="35" r="2.2" fill="${INK}"/><circle cx="95" cy="40" r="2.2" fill="${INK}"/>
      ${eyes(72, 83, 60, 2.6, E)}
      ${smile(78, 66, 2.8, E)}
    </g>`;
  },

  // Beetle — glossy oval elytra with a center seam and shield pronotum, six legs, short clubbed antennae
  beetle: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>`;
    return `
    ${leg("M42 60 q-16 -4 -22 -12")}${leg("M40 72 q-18 0 -24 4")}${leg("M42 84 q-16 6 -20 16")}
    ${leg("M78 60 q16 -4 22 -12")}${leg("M80 72 q18 0 24 4")}${leg("M78 84 q16 6 20 16")}
    <g class="breathe">
      <ellipse cx="60" cy="74" rx="28" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 52 L60 96" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M44 60 Q40 76 46 92 M76 60 Q80 76 74 92" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      <path d="M42 52 Q60 42 78 52 Q78 62 60 62 Q42 62 42 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M50 46 a10 8 0 0 1 20 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M54 40 q-4 -7 -10 -9 M66 40 q4 -7 10 -9" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="43" cy="30" r="2.4" fill="${INK}"/><circle cx="77" cy="30" r="2.4" fill="${INK}"/>
      ${eyes(55, 65, 44, 2.4, E)}
    </g>`;
  },

  // Rhino Beetle — armoured beetle with one big curved head horn and a smaller thoracic horn
  rhinobeetle: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`;
    return `
    ${leg("M42 66 q-16 -3 -22 -12")}${leg("M40 78 q-18 1 -24 6")}${leg("M42 90 q-15 7 -18 16")}
    ${leg("M78 66 q16 -3 22 -12")}${leg("M80 78 q18 1 24 6")}${leg("M78 90 q15 7 18 16")}
    <g class="breathe">
      <ellipse cx="60" cy="80" rx="29" ry="23" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M60 60 L60 100" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M40 58 Q60 46 80 58 Q80 70 60 70 Q40 70 40 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M55 58 Q52 48 58 44 Q60 50 60 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M50 48 a10 8 0 0 1 20 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 44 Q52 26 62 16 Q72 20 66 30 Q60 36 63 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${eyes(55, 65, 46, 2.4, E)}
    </g>`;
  },

  // Stag Beetle — beetle with two enormous branching antler-like mandibles opening at the front
  stagbeetle: (c) => {
    const E = eyeInk(c);
    const leg = (d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`;
    const jaw = `<path d="M52 42 Q40 30 40 18 Q46 22 50 30 Q52 24 58 24" fill="none" stroke="${c.line}" stroke-width="5.2" stroke-linecap="round"/>
      <path d="M52 42 Q40 30 40 18 Q46 22 50 30 Q52 24 58 24" fill="none" stroke="${c.shade}" stroke-width="2.6" stroke-linecap="round"/>`;
    return `
    ${leg("M42 68 q-16 -3 -22 -12")}${leg("M40 80 q-18 1 -24 6")}${leg("M42 92 q-15 7 -18 16")}
    ${leg("M78 68 q16 -3 22 -12")}${leg("M80 80 q18 1 24 6")}${leg("M78 92 q15 7 18 16")}
    <g class="tail-wag">${jaw}${mirror(jaw)}</g>
    <g class="breathe">
      <ellipse cx="60" cy="82" rx="28" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M60 62 L60 100" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M41 60 Q60 50 79 60 Q79 71 60 71 Q41 71 41 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M50 50 a11 9 0 0 1 22 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${eyes(55, 65, 48, 2.6, E)}
    </g>`;
  },

  // Firefly — dark little beetle with a bright glowing lantern at the tail, halo of light
  firefly: (c) => {
    const E = eyeInk(c);
    return `
    ${[52, 66, 80].map((x) => `<path d="M${x} 78 q-2 9 -6 13" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`).join("")}
    <g class="tail-wag">
      <ellipse cx="46" cy="46" rx="16" ry="8" transform="rotate(-18 46 46)" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
      <ellipse cx="70" cy="46" rx="13" ry="7" transform="rotate(-4 70 46)" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
    </g>
    <g class="breathe">
      <circle cx="24" cy="66" r="15" fill="#f7e08a" opacity=".45"/>
      <circle cx="26" cy="66" r="9" fill="#f2c94c" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="54" cy="66" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 50 L54 82" stroke="${c.line}" stroke-width="1.8" opacity=".7"/>
      <path d="M40 54 Q60 44 72 54 Q72 62 56 62 Q40 62 40 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="80" cy="60" r="11" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M85 50 q6 -6 9 -11 M89 54 q7 -3 11 -5" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(77, 85, 59, 2.4, E)}
      ${smile(81, 63, 2.4, E)}
    </g>`;
  },

  // Dragonfly — long slender abdomen, big compound-eyed head, four long gossamer wings held wide
  dragonfly: (c) => {
    const E = eyeInk(c);
    const w = (cx, cy, rot, rx) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="6.5" transform="rotate(${rot} ${cx} ${cy})" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>`;
    return `
    <g class="tail-wag">
      ${w(60, 38, -10, 27)}${w(58, 76, 12, 25)}
      ${mirror(w(60, 38, -10, 27))}${mirror(w(58, 76, 12, 25))}
    </g>
    <g class="breathe">
      <path d="M78 58 Q46 60 16 66 Q46 68 78 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${[62, 50, 38, 27].map((x) => `<path d="M${x} 60 l0 5" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
      <ellipse cx="80" cy="60" rx="11" ry="13" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
    </g>
    <g class="head-tilt">
      <circle cx="94" cy="56" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="90" cy="50" r="5.5" fill="${E}"/><circle cx="99" cy="52" r="5.5" fill="${E}"/>
      <circle cx="91.6" cy="48.2" r="1.7" fill="#fff" opacity=".9"/><circle cx="100.6" cy="50.2" r="1.7" fill="#fff" opacity=".9"/>
      ${smile(94, 60, 2.4, E)}
    </g>`;
  },

  // Grasshopper — long green body, folded jumping hind leg with thick femur, small head with long feelers
  grasshopper: (c) => {
    const E = eyeInk(c);
    return `
    <path d="M56 74 Q46 86 44 98 M60 74 Q54 88 54 100" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    <g class="breathe">
      <path d="M22 70 Q30 56 58 58 Q84 60 92 66 Q84 74 58 74 Q32 76 22 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M30 66 Q54 60 80 65" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
    </g>
    <g class="tail-wag">
      <path d="M36 66 Q48 38 74 50 Q72 66 54 74 Q40 74 36 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M66 50 Q94 54 106 88" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M106 88 l6 -2 M106 88 l-1 6" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 58 Q98 56 98 68 Q98 78 86 76 Q80 68 84 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M95 56 Q101 50 105 45 M97 59 Q103 55 108 51" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(92, 62, 3.2, E)}
      ${smile(96, 68, 2.4, E)}
    </g>`;
  },

  // Cricket — chunky humped body, very long swept-back antennae, powerful hind leg, chirpy face
  cricket: (c) => {
    const E = eyeInk(c);
    return `
    <path d="M28 72 L6 82 M28 76 L8 86" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    <path d="M54 78 Q46 90 44 100 M60 78 Q56 92 56 102" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    <g class="breathe">
      <path d="M24 72 Q26 52 56 52 Q86 54 94 70 Q86 80 56 80 Q30 80 24 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 58 Q60 52 84 62" fill="none" stroke="${c.shade}" stroke-width="1.8" opacity=".7"/>
      <path d="M34 70 Q56 66 82 72" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="tail-wag">
      <path d="M44 68 Q56 46 74 56 Q68 70 54 76 Q46 76 44 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M66 56 Q90 62 102 90" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M102 90 l6 -1 M102 90 l-2 6" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="88" cy="66" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M96 58 Q112 42 118 16 M98 62 Q116 52 120 40" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 63, 3.2, E)}
      ${smile(92, 70, 2.6, E)}
    </g>`;
  },

  // Praying Mantis — triangular head with huge eyes, long neck, folded spiky raptorial arms in prayer
  prayingmantis: (c) => {
    const E = eyeInk(c);
    return `
    <path d="M44 82 Q30 84 22 94 M46 86 Q34 92 28 102 M48 84 Q60 92 62 102" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    <g class="breathe">
      <path d="M38 92 Q30 74 44 66 Q60 60 64 74 Q62 90 50 94 Q42 96 38 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 68 Q64 58 68 48" fill="none" stroke="${c.line}" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M56 68 Q64 58 68 48" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M60 66 Q76 66 80 78" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M80 78 Q72 74 62 76" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M64 74 l-3 3 M69 74 l-3 3 M74 75 l-3 3" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M60 50 L82 42 L74 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 40 Q92 28 100 12 M82 42 Q96 34 106 26" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="66" cy="48" rx="4.6" ry="5.4" fill="${E}"/><circle cx="67.2" cy="46" r="1.6" fill="#fff" opacity=".9"/>
      <ellipse cx="78" cy="46" rx="4.6" ry="5.4" fill="${E}"/><circle cx="79.2" cy="44" r="1.6" fill="#fff" opacity=".9"/>
      ${smile(72, 54, 2.2, E)}
    </g>`;
  },

  // Spider — round abdomen and cephalothorax, eight bent legs, little fangs and a cluster of eyes
  spider: (c) => {
    const E = eyeInk(c);
    const legL = (d) => `${tube(d, c.body, c.line, 2.6)}`;
    const left = [
      "M48 54 Q30 42 20 46 Q14 48 12 54",
      "M46 60 Q26 54 14 58 Q8 60 8 66",
      "M46 68 Q26 70 14 76 Q9 79 8 84",
      "M48 74 Q32 82 24 92 Q21 97 22 102",
    ].map(legL).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">
      <ellipse cx="60" cy="78" rx="24" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 60 Q52 78 60 96 M46 66 Q52 78 46 90 M74 66 Q68 78 74 90" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="52" r="15" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 64 q-3 6 -7 8 M66 64 q3 6 7 8" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      ${eyes(54, 66, 48, 3, E)}
      <circle cx="49" cy="53" r="1.8" fill="${E}"/><circle cx="71" cy="53" r="1.8" fill="${E}"/>
      <circle cx="57" cy="57" r="1.5" fill="${E}"/><circle cx="63" cy="57" r="1.5" fill="${E}"/>
    </g>`;
  },

  // Tarantula — big hairy spider, eight thick fuzzy legs with bristles, fat furry abdomen, bold fangs
  tarantula: (c) => {
    const E = eyeInk(c);
    const hairs = (d, pts) => `${tube(d, c.body, c.line, 4.2)}${pts.map(([x, y, dx, dy]) => `<path d="M${x} ${y} l${dx} ${dy}" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>`).join("")}`;
    const left = [
      ["M46 56 Q26 42 14 46 Q9 47 6 52", [[30, 45, -3, -4], [20, 45, -3, -4]]],
      ["M44 64 Q22 56 10 60 Q5 62 4 68", [[28, 57, -3, -3], [16, 59, -3, -3]]],
      ["M44 72 Q22 74 10 80 Q6 83 6 90", [[26, 74, -3, 3], [15, 79, -3, 3]]],
      ["M46 80 Q30 88 22 100 Q20 104 22 108", [[32, 88, -3, 4], [25, 98, -3, 4]]],
    ].map(([d, pts]) => hairs(d, pts)).join("");
    return `
    ${left}${mirror(left)}
    <g class="breathe">${pom(60, 80, 24, c.body, c.line, 16, 2.4)}</g>
    <g class="head-tilt">
      ${pom(60, 54, 16, c.shade, c.line, 12, 2.4)}
      <path d="M53 66 q-3 8 -8 10 M67 66 q3 8 8 10" fill="none" stroke="${c.line}" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M45 76 l0 5 M75 76 l0 5" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
      ${eyes(53, 67, 50, 3.2, E)}
      <circle cx="60" cy="47" r="1.8" fill="${E}"/><circle cx="53" cy="45" r="1.5" fill="${E}"/><circle cx="67" cy="45" r="1.5" fill="${E}"/>
    </g>`;
  },

  // Scorpion — two big pincer claws forward, eight legs, segmented tail curling up with a barbed stinger
  scorpion: (c) => {
    const E = eyeInk(c);
    const claw = `<path d="M40 66 Q22 60 14 50 Q10 44 16 40" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M40 66 Q22 60 14 50 Q10 44 16 40" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M22 52 Q10 46 6 36 Q4 30 12 30 Q22 32 24 44 Q24 52 20 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M16 40 Q8 40 5 34" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    return `
    <path d="M52 80 Q40 88 34 98 M58 82 Q50 92 46 102 M64 82 Q60 94 58 104" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    ${claw}${mirror(claw)}
    <g class="tail-wag">
      <path d="M78 76 Q100 72 104 50 Q106 34 92 28" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M78 76 Q100 72 104 50 Q106 34 92 28" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>
      ${[[97, 66], [104, 52], [101, 38]].map(([x, y]) => `<path d="M${x - 4} ${y} l8 0" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>`).join("")}
      <path d="M92 28 Q82 24 84 16 Q90 20 96 22 Q90 26 92 28 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 16 l-5 -4" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="58" cy="74" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[46, 56, 66, 76].map((x) => `<path d="M${x} 62 Q${x} 74 ${x} 86" stroke="${c.shade}" stroke-width="1.4" opacity=".55"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M40 68 Q52 60 66 68 Q52 76 40 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eyes(48, 58, 68, 2.4, E)}
    </g>`;
  },

  // Snail — soft gliding foot, tall coiled spiral shell, two eye-stalk tentacles, contented smile
  snail: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      <path d="M14 88 Q14 78 30 76 Q60 72 84 74 Q98 76 96 86 Q92 94 60 94 Q22 96 14 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 90 Q56 96 92 88" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="tail-wag">
      <circle cx="52" cy="56" r="30" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M74.3 44.7 L75.8 49.7 L76.3 54.8 L75.6 59.9 L74.0 64.6 L71.4 68.8 L68.0 72.3 L64.1 75.0 L59.7 76.8 L55.1 77.6 L50.5 77.4 L46.2 76.3 L42.2 74.3 L38.8 71.6 L36.1 68.3 L34.2 64.5 L33.2 60.5 L33.0 56.5 L33.7 52.5 L35.1 48.9 L37.3 45.7 L40.0 43.1 L43.1 41.2 L46.5 40.0 L50.1 39.6 L53.5 39.9 L56.8 40.9 L59.6 42.5 L62.1 44.7 L63.9 47.2 L65.2 50.1 L65.8 53.0 L65.8 56.0 L65.1 58.8 L63.9 61.3 L62.2 63.5 L60.2 65.2 L57.9 66.4 L55.5 67.1 L53.1 67.2 L50.7 66.9 L48.6 66.0 L46.7 64.8 L45.3 63.2 L44.2 61.4 L43.5 59.6 L43.3 57.6 L43.5 55.8 L44.1 54.1 L45.0 52.6 L46.1 51.5 L47.4 50.6 L48.8 50.1 L50.2 49.9 L51.6 50.0 L52.8 50.4 L53.8 51.0 L54.7 51.8 L55.2 52.7 L55.6 53.7 L55.6 54.6 L55.5 55.4 L55.2 56.2 L54.8 56.7 L54.2 57.1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 78 Q98 78 100 64 Q102 54 92 52 Q84 52 82 60 Q82 72 84 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M96 54 Q104 40 106 30 M90 52 Q94 40 94 32" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <circle cx="106" cy="28" r="3.2" fill="${E}"/><circle cx="94" cy="30" r="3.2" fill="${E}"/>
      <circle cx="107" cy="26.8" r="1.2" fill="#fff" opacity=".9"/><circle cx="95" cy="28.8" r="1.2" fill="#fff" opacity=".9"/>
      ${smile(96, 66, 2.6, E)}
    </g>`;
  },

  // Caterpillar — arch of chubby ringed segments with tiny prolegs, cute front face and stub antennae
  caterpillar: (c) => {
    const E = eyeInk(c);
    const segs = [[24, 78], [35, 68], [47, 62], [59, 60], [71, 62], [82, 68], [92, 78]];
    const legs = segs.slice(0, 6).map(([x, y]) => `<path d="M${x} ${y + 8} q-1 6 -4 9 M${x + 4} ${y + 8} q1 6 4 9" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`).join("");
    const body = segs.slice(0, 6).map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="11" fill="${i % 2 ? c.shade : c.body}" stroke="${c.line}" stroke-width="2.4"/>`).join("");
    return `
    ${legs}
    <g class="breathe">${body}</g>
    <g class="head-tilt">
      <circle cx="92" cy="76" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M88 65 q-2 -8 -6 -11 M96 65 q2 -8 6 -11" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="82" cy="52" r="2.2" fill="${INK}"/><circle cx="102" cy="52" r="2.2" fill="${INK}"/>
      ${eyes(87, 97, 74, 2.8, E)}
      ${smile(92, 80, 3, E)}
    </g>`;
  },

  // Centipede — long undulating chain of segments with a leg pair on each, feelers and eyes up front
  centipede: (c) => {
    const E = eyeInk(c);
    const segs = [[20, 68], [32, 60], [44, 66], [56, 58], [68, 64], [80, 58], [92, 64]];
    const legs = segs.map(([x, y]) => `<path d="M${x} ${y + 7} q-4 8 -8 11 M${x} ${y + 7} q4 8 8 11 M${x} ${y - 7} q-4 -6 -8 -8 M${x} ${y - 7} q4 -6 8 -8" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`).join("");
    const body = segs.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="${i === segs.length - 1 ? 12 : 9.5}" fill="${i % 2 ? c.shade : c.body}" stroke="${c.line}" stroke-width="2.4"/>`).join("");
    return `
    ${legs}
    <g class="breathe">${body}</g>
    <g class="head-tilt">
      <path d="M99 56 q12 -8 14 -18 M101 62 q13 -3 18 -8" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eyes(88, 97, 62, 2.6, E)}
      ${smile(92, 68, 2.4, E)}
    </g>`;
  },

  // Wasp — sleek striped body pinched at a narrow waist, sharp abdomen stinger, angular head, feelers
  wasp: (c) => {
    const E = eyeInk(c);
    return `
    ${[52, 68, 82].map((x) => `<path d="M${x} 80 q-3 9 -7 13" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`).join("")}
    <g class="tail-wag">
      <ellipse cx="48" cy="42" rx="19" ry="9" transform="rotate(-20 48 42)" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
      <ellipse cx="72" cy="42" rx="14" ry="7" transform="rotate(-4 72 42)" fill="${WING}" stroke="${c.line}" stroke-width="1.6" opacity=".85"/>
    </g>
    <g class="breathe">
      <path d="M18 62 L3 66 L18 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M16 66 Q30 48 46 52 Q57 55 57 66 Q57 78 46 80 Q30 84 16 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[[30, 13], [42, 15], [52, 10]].map(([x, ry]) => `<ellipse cx="${x}" cy="66" rx="3.2" ry="${ry}" fill="${INK}"/>`).join("")}
      <path d="M57 66 Q62 62 68 64" fill="none" stroke="${c.line}" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M57 66 Q62 62 68 64" fill="none" stroke="${c.body}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="70" cy="64" rx="11" ry="12" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="head-tilt">
      <circle cx="88" cy="60" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M94 49 q6 -6 9 -12 M98 53 q8 -3 12 -6" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      <circle cx="103" cy="35" r="2.2" fill="${INK}"/><circle cx="110" cy="46" r="2.2" fill="${INK}"/>
      ${eyes(84, 93, 58, 2.6, E)}
      ${smile(88, 64, 2.6, E)}
    </g>`;
  },
};

export const ROSTER_BUGS = [
  { n: "Honeybee",          e: "🐝", tier: 1, float: true },
  { n: "Bumblebee",         e: "🐝", tier: 1, float: true },
  { n: "Ladybug",           e: "🐞", tier: 1, float: false },
  { n: "Butterfly",         e: "🦋", tier: 1, float: true },
  { n: "Monarch Butterfly", e: "🦋", tier: 2, float: true },
  { n: "Moth",              e: "🦋", tier: 2, float: true },
  { n: "Ant",               e: "🐜", tier: 1, float: false },
  { n: "Beetle",            e: "🪲", tier: 1, float: false },
  { n: "Rhino Beetle",      e: "🪲", tier: 2, float: false },
  { n: "Stag Beetle",       e: "🪲", tier: 3, float: false },
  { n: "Firefly",           e: "✨", tier: 2, float: true },
  { n: "Dragonfly",         e: "🪰", tier: 2, float: true },
  { n: "Grasshopper",       e: "🦗", tier: 1, float: false },
  { n: "Cricket",           e: "🦗", tier: 1, float: false },
  { n: "Praying Mantis",    e: "🙏", tier: 3, float: false },
  { n: "Spider",            e: "🕷️", tier: 2, float: false },
  { n: "Tarantula",         e: "🕷️", tier: 3, float: false },
  { n: "Scorpion",          e: "🦂", tier: 3, float: false },
  { n: "Snail",             e: "🐌", tier: 1, float: false },
  { n: "Caterpillar",       e: "🐛", tier: 1, float: false },
  { n: "Centipede",         e: "🪱", tier: 2, float: false },
  { n: "Wasp",              e: "🐝", tier: 2, float: true },
];
