// pets-art/sea.js — BESPOKE hand-drawn SVG art for the SEA CREATURES batch of the NADO Pets roster.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (underside/accent), c.line (outline). Aquatic => float:true, bodies
// oriented horizontally (head to the RIGHT for the swimmers). Helpers from ../pets-draw.js.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

export const ART_SEA = {
  // Clownfish — stout oval, three white bands, rounded fins, forked tail, chubby cheeks
  clownfish: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M32 62 L10 44 Q19 62 10 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M20 54 L14 62 L20 70" fill="none" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="62" rx="31" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 44 Q56 33 70 42 Q60 45 54 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M44 80 Q54 90 64 80 Q56 82 50 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 90 Q56 96 64 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M72 44 Q77 62 72 80 L64 79 Q69 62 64 45 Z" fill="#fff" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 47 Q56 62 52 77 L44 74 Q48 62 44 50 Z" fill="#fff" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 50 Q92 56 88 64 Q92 70 84 74" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      ${eye(82, 58, 3.2, E)}
      ${smile(87, 65, 2.6, E)}
    </g>`;
  },

  // Goldfish — round belly, big flowing triple-lobed veil tail, tall dorsal, bubble eye
  goldfish: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M34 62 Q14 40 7 48 Q17 58 12 62 Q17 66 7 76 Q14 84 34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M34 62 Q20 50 12 48 M34 62 Q20 74 12 76" fill="none" stroke="${c.line}" stroke-width="1.3"/>
    </g>
    <g class="breathe">
      <ellipse cx="64" cy="62" rx="27" ry="23" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 40 Q64 30 78 42 Q66 42 58 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M52 84 Q62 92 72 84 Q64 85 58 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M44 62 q10 6 22 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".7"/>
    </g>
    <g class="head-tilt">
      ${eye(82, 56, 3.6, E)}
      <ellipse cx="90" cy="66" rx="2.6" ry="3" fill="none" stroke="${E}" stroke-width="1.4"/>
    </g>`;
  },

  // Pufferfish — inflated spiky ball, tiny fins, pouty mouth, wide innocent eyes
  pufferfish: (c) => {
    const E = eyeInk(c);
    const spikes = Array.from({ length: 16 }, (_, i) => {
      const a = i / 16 * 2 * Math.PI;
      const bx1 = (60 + 23 * Math.cos(a + 0.12)).toFixed(1), by1 = (62 + 23 * Math.sin(a + 0.12)).toFixed(1);
      const bx2 = (60 + 23 * Math.cos(a - 0.12)).toFixed(1), by2 = (62 + 23 * Math.sin(a - 0.12)).toFixed(1);
      const tx = (60 + 31 * Math.cos(a)).toFixed(1), ty = (62 + 31 * Math.sin(a)).toFixed(1);
      return `<path d="M${bx1} ${by1} L${tx} ${ty} L${bx2} ${by2} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>`;
    }).join("");
    return `
    <g class="tail-wag"><path d="M34 62 Q26 54 24 62 Q26 70 34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/></g>
    <g class="breathe">
      ${spikes}
      <circle cx="60" cy="62" r="24" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 68 Q60 84 80 68 Q60 78 40 68 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M84 56 q8 6 0 12" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
    </g>
    <g class="head-tilt">
      ${eyes(52, 68, 56, 3.6, E)}
      <ellipse cx="60" cy="70" rx="4" ry="3" fill="none" stroke="${E}" stroke-width="1.8"/>
    </g>`;
  },

  // Shark — torpedo body, tall triangular dorsal, crescent tail, gill slits, toothy grin
  shark: (c) => {
    const E = eyeInk(c);
    const teeth = Array.from({ length: 5 }, (_, i) => `<path d="M${80 + i * 4} 70 l2 4 l2 -4 Z" fill="#fff" stroke="${c.line}" stroke-width="0.8"/>`).join("");
    return `
    <g class="tail-wag"><path d="M32 62 L12 42 Q20 62 12 82 L30 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 62 Q42 46 70 46 Q94 48 104 60 Q96 74 70 78 Q42 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 70 Q66 82 96 66 Q66 78 40 70 Z" fill="${c.shade}"/>
      <path d="M56 47 L64 26 L74 47 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 76 L58 90 L68 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 52 q-2 8 0 16 M83 52 q-2 8 0 16 M88 54 q-2 6 0 12" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M78 70 Q90 76 102 66" fill="none" stroke="${c.line}" stroke-width="1.8"/>
      ${teeth}
      ${eye(92, 58, 2.6, E)}
    </g>`;
  },

  // Dolphin — arched streamlined body, rounded melon, distinct narrow beak (rostrum) with smile, falcate dorsal
  dolphin: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M26 64 Q12 56 6 50 Q16 63 6 78 Q14 71 28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 66 Q32 48 58 47 Q78 47 90 55 L104 53 Q110 55 106 60 Q99 63 89 60 Q85 66 79 68 Q58 80 40 76 Q30 73 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 72 Q62 82 84 66 Q62 78 40 72 Z" fill="${c.shade}"/>
      <path d="M56 47 Q59 29 46 32 Q54 40 52 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 72 Q56 87 71 81 Q62 76 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M89 59 Q97 58 106 58" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      <path d="M83 50 q4 -3 7 -1" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".6"/>
      ${eye(82, 55, 2.6, E)}
    </g>`;
  },

  // Orca — ROBUST blunt body, VERY tall straight dorsal, bold white eye-patch + saddle + belly, paddle pec fin
  orca: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M24 62 Q11 51 5 47 Q13 62 5 77 Q11 73 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q28 46 52 44 Q86 42 106 60 Q98 74 86 76 Q84 80 74 80 Q40 82 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 71 Q72 86 104 62 Q72 82 42 71 Z" fill="#fff" stroke="${c.line}" stroke-width="1.3"/>
      <path d="M58 44 L59 16 L78 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M60 73 Q68 90 82 76 Q70 74 66 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.1" stroke-linejoin="round"/>
      <ellipse cx="50" cy="56" rx="11" ry="6.5" fill="#fff" opacity=".9" transform="rotate(-16 50 56)"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="93" cy="55" rx="6.5" ry="4.4" fill="#fff" stroke="${c.line}" stroke-width="1.2" transform="rotate(-12 93 55)"/>
      <path d="M88 67 q9 4 15 -3" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(93, 56, 2.4, INK)}
    </g>`;
  },

  // Blue Whale — VERY long low body, broad blunt head, ventral throat pleats, tiny nub dorsal near tail, spout
  bluewhale: (c) => {
    const E = eyeInk(c);
    const pleats = Array.from({ length: 8 }, (_, i) => `<path d="M${64 + i * 6} 74 q0 8 3 12" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("");
    return `
    <g class="tail-wag"><path d="M16 62 Q6 50 2 47 Q9 62 2 77 Q6 74 16 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M6 55 Q-2 62 6 69" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/></g>
    <g class="breathe">
      <path d="M14 62 Q26 48 68 47 Q104 47 116 60 Q110 65 102 65 Q72 78 40 76 Q20 72 14 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 72 Q76 82 102 65 Q76 78 40 72 Z" fill="${c.shade}"/>
      ${pleats}
      <path d="M44 49 Q47 42 52 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M104 47 q-3 -11 -7 -15 M104 47 q3 -11 7 -14 M104 47 q0 -12 1 -17" fill="none" stroke="#bcd6ea" stroke-width="2" stroke-linecap="round" opacity=".85"/>
      <path d="M100 65 q7 3 13 -3" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(104, 59, 2.3, E)}
    </g>`;
  },

  // Octopus — big domed head, huge eyes, eight curling suckered arms fanning out
  octopus: (c) => {
    const E = eyeInk(c);
    const arms = [
      "M40 74 Q22 82 18 98 Q16 106 24 104", "M48 80 Q36 96 40 108",
      "M56 82 Q52 100 62 108", "M64 82 Q66 102 78 106",
      "M72 80 Q86 94 84 108", "M80 74 Q98 82 102 98 Q104 106 96 104",
      "M34 68 Q16 68 10 78", "M86 68 Q104 68 110 78",
    ];
    const suckers = arms.map((d) => {
      const m = d.match(/M(\d+) (\d+)/);
      return `<circle cx="${+m[1]}" cy="${+m[2] + 6}" r="1.6" fill="${c.shade}"/>`;
    }).join("");
    return `
    <g class="tail-wag">${arms.map((d) => tube(d, c.body, c.line, 7)).join("")}${suckers}</g>
    <g class="breathe">
      <path d="M32 58 Q32 26 60 26 Q88 26 88 58 Q88 74 60 74 Q32 74 32 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M42 34 Q52 28 60 30 Q50 34 46 40 Z" fill="#fff" opacity=".25"/>
    </g>
    <g class="head-tilt">
      ${eyes(50, 70, 50, 4.4, E)}
      ${smile(60, 60, 4, E)}
    </g>`;
  },

  // Squid — long torpedo mantle with twin tail fins, huge eyes, ten trailing arms + feeders
  squid: (c) => {
    const E = eyeInk(c);
    const arms = ["M78 70 Q96 76 104 90", "M80 66 Q100 68 108 78", "M78 60 Q100 60 110 62",
      "M76 74 Q92 84 96 98", "M74 78 Q84 92 82 104"];
    const feeders = ["M82 62 Q108 58 114 44", "M82 72 Q106 82 112 96"];
    return `
    <g class="tail-wag">
      <path d="M20 62 L34 50 Q40 62 34 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${feeders.map((d) => tube(d, c.shade, c.line, 4)).join("")}
      ${feeders.map((d) => { const p = d.match(/Q\d+ \d+ (\d+) (\d+)/); return `<ellipse cx="${+p[1]}" cy="${+p[2]}" rx="4" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`; }).join("")}
      ${arms.map((d) => tube(d, c.body, c.line, 5)).join("")}
    </g>
    <g class="breathe">
      <path d="M30 62 Q34 46 60 46 Q80 46 84 62 Q80 78 60 78 Q34 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 52 Q52 48 62 50 Q50 54 46 58 Z" fill="#fff" opacity=".22"/>
    </g>
    <g class="head-tilt">
      ${eye(66, 60, 5, E)}
      <path d="M74 60 q6 4 10 2" fill="none" stroke="${c.line}" stroke-width="1.4"/>
    </g>`;
  },

  // Jellyfish — translucent domed bell with scalloped rim, drifting frilly tentacles, gentle face
  jellyfish: (c) => {
    const E = eyeInk(c);
    const tents = ["M40 66 Q36 84 42 100", "M50 68 Q48 88 52 104", "M60 68 Q60 90 60 106",
      "M70 68 Q72 88 68 104", "M80 66 Q84 84 78 100"];
    const frills = ["M34 64 Q34 78 40 88", "M86 64 Q86 78 80 88"];
    return `
    <g class="tail-wag">
      ${tents.map((d) => tube(d, c.shade, c.line, 4)).join("")}
      ${frills.map((d) => tube(d, c.body, c.line, 3)).join("")}
    </g>
    <g class="breathe">
      <path d="M30 60 Q30 30 60 30 Q90 30 90 60 Q90 64 84 64 Q80 70 74 64 Q68 70 62 64 Q56 70 50 64 Q44 70 38 64 Q32 64 30 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M42 40 Q54 33 64 36 Q52 40 48 46 Z" fill="#fff" opacity=".3"/>
      <ellipse cx="60" cy="52" rx="14" ry="9" fill="${c.shade}" opacity=".35"/>
    </g>
    <g class="head-tilt">
      ${eyes(52, 68, 50, 3, E)}
      ${smile(60, 56, 3, E)}
    </g>`;
  },

  // Seahorse — upright S-body with segment ridges, horse head + tubular snout, spiny coronet, dorsal fin, coiled tail
  seahorse: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M52 78 Q40 82 42 92 Q44 100 54 98 Q60 96 58 90 Q56 94 50 93 Q46 92 47 87 Q48 82 54 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M52 32 Q68 32 70 48 Q71 60 60 66 Q50 71 52 81 L44 82 Q40 70 50 62 Q60 57 58 47 Q56 39 47 41 Q48 33 52 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M66 42 Q76 46 73 58 Q69 51 63 50 Q66 46 66 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[44,51,58,64].map(y=>`<path d="M48 ${y} q7 1 11 -2" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".65"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M49 31 l-3 -7 M54 29 l0 -8 M59 30 l4 -6" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M49 33 Q47 24 55 23 Q63 24 63 33 Q63 41 54 40 Q46 40 49 33 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 35 Q82 33 86 41 Q78 44 62 41 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(56, 33, 2.6, E)}
    </g>`;
  },

  // Sea Turtle — domed patterned shell, FOUR paddle flippers (2 front, 2 rear), head + short tail, hexagon scutes
  seaturtle: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M74 48 Q86 35 94 39 Q86 50 74 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M74 76 Q86 89 94 85 Q86 74 74 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 50 Q32 39 24 43 Q33 53 46 57 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 74 Q32 85 24 81 Q33 71 46 67 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M32 62 Q22 60 19 62 Q22 65 32 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="58" cy="62" rx="26" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M58 47 L71 56 L66 70 L50 70 L45 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M58 47 L58 42 M71 56 L81 53 M66 70 L71 79 M50 70 L45 79 M45 56 L35 53" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".8"/>
      <path d="M34 62 Q58 76 82 62" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="90" cy="62" rx="10" ry="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      ${eye(93, 60, 2.4, E)}
      ${smile(96, 64, 2.2, E)}
    </g>`;
  },

  // Crab — wide flat carapace, two big pincer claws, walking legs, eyes on stalks
  crab: (c) => {
    const E = eyeInk(c);
    const leg = (i) => `<path d="M${42 - i * 2} ${64 + i * 4} Q${28 - i * 3} ${68 + i * 5} ${22 - i * 3} ${78 + i * 4}" fill="none" stroke="${c.line}" stroke-width="3.6" stroke-linecap="round"/>`;
    const legs = [0, 1, 2].map(leg).join("");
    const claw = `
      <path d="M42 60 Q30 54 22 58" fill="none" stroke="${c.line}" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M42 60 Q30 54 22 58" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>
      <path d="M26 47 Q4 43 5 60 Q7 69 21 67 Q12 62 24 60 Q12 57 26 53 Q30 50 26 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`;
    return `
    <g class="tail-wag">${legs}${mirror(legs)}</g>
    <g class="breathe">
      <path d="M30 66 Q30 48 60 48 Q90 48 90 66 Q90 78 60 80 Q30 78 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M44 70 q16 8 32 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      <circle cx="46" cy="60" r="2" fill="${c.shade}"/><circle cx="74" cy="60" r="2" fill="${c.shade}"/>
    </g>
    ${claw}${mirror(claw)}
    <g class="head-tilt">
      <path d="M52 50 L50 40 M68 50 L70 40" stroke="${c.line}" stroke-width="2"/>
      ${eyes(50, 70, 40, 3, E)}
      ${smile(60, 66, 4, E)}
    </g>`;
  },

  // Lobster — segmented armored body, giant front pincers, fan tail, long antennae, tucked legs
  lobster: (c) => {
    const E = eyeInk(c);
    const segs = Array.from({ length: 4 }, (_, i) => `<path d="M${34 + i * 8} 52 q-2 10 0 20" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".7"/>`).join("");
    const legs = Array.from({ length: 3 }, (_, i) => `<path d="M${58 + i * 8} 74 q2 8 -2 14" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`).join("");
    const claw = `
      <path d="M76 58 Q88 54 94 58" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M76 58 Q88 54 94 58" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
      <path d="M92 48 Q104 50 104 58 Q98 58 92 62 Q100 56 92 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`;
    return `
    <g class="tail-wag">
      <path d="M34 62 Q16 48 6 52 Q17 62 6 72 Q16 76 34 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M30 62 L10 55 M30 62 L6 62 M30 62 L10 69" fill="none" stroke="${c.line}" stroke-width="1.2"/>
      ${legs}${legs.replace(/74 q2 8 -2 14/g, "50 q2 -8 -2 -14")}
    </g>
    <g class="breathe">
      <path d="M30 62 Q30 50 56 50 Q82 50 88 62 Q82 74 56 74 Q30 74 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${segs}
      <path d="M40 68 q20 6 40 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M84 54 Q100 40 112 30 M84 60 Q102 50 114 44" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(84, 56, 2.6, E)}
    </g>
    ${claw}`;
  },

  // Starfish — five chunky rounded arms, tube-foot dots, cheerful centered face
  starfish: (c) => {
    const E = eyeInk(c);
    const R = 34, r = 14, pts = [];
    for (let i = 0; i < 10; i++) { const rad = i % 2 ? r : R; const a = (-90 + i * 36) * Math.PI / 180; pts.push(`${(60 + rad * Math.cos(a)).toFixed(1)} ${(62 + rad * Math.sin(a)).toFixed(1)}`); }
    const dots = Array.from({ length: 5 }, (_, i) => { const a = (-90 + i * 72) * Math.PI / 180; return [0.5, 0.78].map((t) => `<circle cx="${(60 + R * t * Math.cos(a)).toFixed(1)}" cy="${(62 + R * t * Math.sin(a)).toFixed(1)}" r="1.8" fill="${c.shade}"/>`).join(""); }).join("");
    return `
    <g class="breathe">
      <path d="M${pts.join(" L")} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M${pts.filter((_, i) => i % 2 === 0).map((p) => { const [x, y] = p.split(" "); return `${(60 + (x - 60) * 0.62).toFixed(1)} ${(62 + (y - 62) * 0.62).toFixed(1)}`; }).join(" L")} Z" fill="${c.shade}" opacity=".4"/>
      ${dots}
    </g>
    <g class="head-tilt">
      ${eyes(53, 67, 58, 3, E)}
      ${smile(60, 64, 3.4, E)}
    </g>`;
  },

  // Seal — smooth plump body, big soulful eyes, whiskered snout, small fore-flippers, tail flukes
  seal: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag"><path d="M28 68 Q14 62 8 56 Q16 68 8 78 Q16 76 28 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 68 Q34 50 60 50 Q82 50 92 58 Q98 62 96 70 Q90 82 60 82 Q34 82 26 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 78 Q64 86 90 72 Q64 82 40 78 Z" fill="${c.shade}"/>
      <path d="M52 78 Q56 90 66 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M76 52 Q98 48 100 62 Q100 74 84 74 Q74 72 76 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="98" cy="64" rx="4.5" ry="3.6" fill="${c.shade}"/>
      <ellipse cx="99" cy="63" rx="1.8" ry="1.5" fill="${INK}"/>
      <path d="M94 66 l10 1 M94 69 l10 -1" stroke="${c.line}" stroke-width="0.9" opacity=".8"/>
      ${eyes(84, 92, 58, 3.2, E)}
    </g>`;
  },

  // Walrus — hefty body, drooping whiskered muzzle, two long ivory tusks, small eyes, flippers
  walrus: (c) => {
    const E = eyeInk(c);
    const whisk = Array.from({ length: 4 }, (_, i) => `<path d="M84 ${68 + i * 1.5} q12 ${i} 16 ${1 + i}" fill="none" stroke="${c.line}" stroke-width="0.9" opacity=".8"/>`).join("");
    return `
    <g class="tail-wag"><path d="M26 66 Q12 60 6 54 Q14 66 6 78 Q14 74 26 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 66 Q32 46 60 46 Q84 46 92 56 Q98 60 96 70 Q88 84 58 84 Q32 84 24 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M38 80 Q62 88 90 72 Q62 84 38 80 Z" fill="${c.shade}"/>
      <path d="M48 80 Q52 92 62 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 50 Q100 46 102 60 Q102 70 90 72 Q80 70 78 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="92" cy="66" rx="9" ry="7" fill="${c.shade}"/>
      <path d="M88 70 Q86 92 82 94 Q80 90 82 72 Z" fill="#f2e6c8" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M96 70 Q98 92 94 94 Q90 90 92 72 Z" fill="#f2e6c8" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="94" cy="62" rx="1.6" ry="1.4" fill="${INK}"/>
      ${whisk}
      ${eyes(82, 92, 54, 2.6, E)}
    </g>`;
  },

  // Stingray — flat kite disc with rippling wings, top-mounted eyes, spotted back, long barbed tail
  stingray: (c) => {
    const E = eyeInk(c);
    const spots = [[62, 56], [72, 60], [54, 66], [66, 68]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2" fill="${c.shade}"/>`).join("");
    return `
    <g class="tail-wag">
      ${tube("M32 66 Q18 74 12 92 Q10 100 16 100", c.body, c.line, 4)}
      <path d="M14 96 l-4 6 l6 -2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M98 62 Q84 44 60 42 Q38 44 30 62 Q38 80 60 82 Q84 80 98 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M30 62 Q24 58 22 62 Q24 66 30 62 M30 62 Q28 56 32 52 M30 62 Q28 68 32 72" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
      ${spots}
    </g>
    <g class="head-tilt">
      <ellipse cx="84" cy="55" rx="3.4" ry="2.6" fill="${c.shade}"/><ellipse cx="84" cy="69" rx="3.4" ry="2.6" fill="${c.shade}"/>
      ${eye(84, 55, 2, E)}${eye(84, 69, 2, E)}
      ${smile(94, 62, 2.4, E)}
    </g>`;
  },

  // Anglerfish — round gaping body, jagged glass teeth, tiny eye, dangling glowing lure on a stalk
  anglerfish: (c) => {
    const E = eyeInk(c);
    const teeth = Array.from({ length: 6 }, (_, i) => `<path d="M${74 + i * 4} 60 l1.6 5 l1.8 -5 Z" fill="#fff" stroke="${c.line}" stroke-width="0.8"/>`).join("");
    const lowteeth = Array.from({ length: 5 }, (_, i) => `<path d="M${76 + i * 4} 76 l1.6 -5 l1.8 5 Z" fill="#fff" stroke="${c.line}" stroke-width="0.8"/>`).join("");
    return `
    <g class="tail-wag"><path d="M30 62 Q18 52 12 54 Q20 62 12 70 Q18 72 30 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q30 40 58 40 Q86 42 92 60 Q86 82 58 84 Q30 82 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 74 Q60 86 84 72 Q60 80 40 74 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M46 44 Q52 34 58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6"/>
    </g>
    <g class="head-tilt">
      <path d="M56 58 Q76 52 92 62 Q76 78 56 70 Q52 64 56 58 Z" fill="${INK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${teeth}${lowteeth}
      ${eye(64, 50, 2.6, "#e9edf2")}
      <path d="M58 40 Q52 20 68 16" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <circle cx="70" cy="14" r="6" fill="#f2c94c" stroke="${c.line}" stroke-width="1.6"/>
      <circle cx="70" cy="14" r="10" fill="#f2c94c" opacity=".28"/>
      <circle cx="68" cy="12" r="1.8" fill="#fff" opacity=".9"/>
    </g>`;
  },

  // Narwhal — stocky body, BULBOUS melon forehead, NO dorsal fin, long spiral ivory tusk (the signature), fluke
  narwhal: (c) => {
    const E = eyeInk(c);
    const spiral = Array.from({ length: 8 }, (_, i) => `<path d="M${99 + i * 2.6} ${55 - i * 0.3} l2.4 4.4" stroke="${c.line}" stroke-width="1" opacity=".85"/>`).join("");
    return `
    <g class="tail-wag"><path d="M22 62 Q10 50 5 46 Q14 62 5 78 Q10 74 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M20 62 Q30 47 58 46 Q86 46 100 60 Q94 76 66 78 Q34 80 20 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M38 72 Q66 82 96 66 Q66 78 38 72 Z" fill="${c.shade}"/>
      <path d="M48 76 Q52 88 62 79 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${[[44,55],[54,58],[64,55],[74,58]].map(([x,y])=>`<ellipse cx="${x}" cy="${y}" rx="2.6" ry="1.8" fill="${c.shade}" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M96 57 L122 45 L98 63 Z" fill="#f2e6c8" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${spiral}
      <path d="M88 67 q7 3 12 -2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(88, 58, 2.5, E)}
    </g>`;
  },
};

export const ROSTER_SEA = [
  { n: "Clownfish",  e: "🐠", tier: 1, float: true },
  { n: "Goldfish",   e: "🐟", tier: 1, float: true },
  { n: "Pufferfish", e: "🐡", tier: 2, float: true },
  { n: "Shark",      e: "🦈", tier: 3, float: true },
  { n: "Dolphin",    e: "🐬", tier: 2, float: true },
  { n: "Orca",       e: "🐋", tier: 3, float: true },
  { n: "Blue Whale", e: "🐳", tier: 4, float: true },
  { n: "Octopus",    e: "🐙", tier: 2, float: true },
  { n: "Squid",      e: "🦑", tier: 2, float: true },
  { n: "Jellyfish",  e: "🪼", tier: 2, float: true },
  { n: "Seahorse",   e: "🐴", tier: 2, float: true },
  { n: "Sea Turtle", e: "🐢", tier: 2, float: true },
  { n: "Crab",       e: "🦀", tier: 1, float: true },
  { n: "Lobster",    e: "🦞", tier: 2, float: true },
  { n: "Starfish",   e: "⭐", tier: 1, float: true },
  { n: "Seal",       e: "🦭", tier: 2, float: true },
  { n: "Walrus",     e: "🦣", tier: 3, float: true },
  { n: "Stingray",   e: "🌊", tier: 2, float: true },
  { n: "Anglerfish", e: "🎣", tier: 3, float: true },
  { n: "Narwhal",    e: "🦄", tier: 4, float: true },
];
