// pets-art/dinos.js — BESPOKE hand-drawn SVG art for the DINOSAURS & PREHISTORIC animals batch.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">. Palette-driven:
//   c.body (main fill) · c.shade (sail/underside/armor/plates) · c.line (outline). Tusks/horns/claws/teeth
//   use fixed warm ivory or #fff; nose INK. Torso in .breathe, head/face in .head-tilt, tails/wings/plates
//   in .tail-wag. Fliers/swimmers set float:true and are drawn horizontally. Keys are name-slugs and match
//   every ROSTER_DINOS `n` slugified. Helpers from ../pets-draw.js.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const IVORY = "#f0e6d2";   // tusks / horns / big claws / sabers
const HORN  = "#d9c9a3";   // beaks / duck-bills
const TEETH = "#ffffff";

export const ART_DINOS = {
  // ── Tyrannosaurus — colossal head, gaping toothy jaws, absurd tiny arms, pillar legs, thick tail ──
  tyrannosaurus: (c) => `
    <g class="tail-wag"><path d="M42 74 Q18 70 8 86 Q13 90 20 87 Q32 80 48 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 84 q12 -4 24 -3" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/></g>
    <path d="M56 84 Q52 98 56 106 L66 106 Q68 98 66 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M40 78 Q40 56 60 54 Q84 54 84 74 Q84 88 62 88 Q44 88 40 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 82 q16 6 30 0" fill="${c.shade}" opacity=".5"/></g>
    <path d="M60 82 Q54 98 58 108 L70 108 Q74 98 70 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M58 108 l-6 3 M62 108 l0 4 M67 108 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M74 66 q8 4 6 12" fill="none" stroke="${c.line}" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M74 66 q8 4 6 12" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>
    <path d="M80 78 l2 3 M80 78 l3 1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M66 40 Q78 30 96 36 Q108 40 106 50 L92 52 Q80 52 70 54 Q62 50 66 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 56 Q86 64 102 60 L104 66 Q88 72 74 66 Q70 60 74 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 60 q10 4 22 1" fill="${c.shade}" opacity=".5"/>
      <path d="M76 53 l2 5 l2 -5 M84 53 l2 6 l2 -6 M92 52 l2 5 l2 -5 M100 51 l1.5 4 l2 -4" fill="${TEETH}" stroke="${c.line}" stroke-width="1"/>
      <path d="M80 62 l2 -4 l2 4 M90 63 l2 -4 l2 4 M98 62 l1.5 -3 l2 3" fill="${TEETH}" stroke="${c.line}" stroke-width="1"/>
      <ellipse cx="100" cy="43" rx="1.6" ry="1.2" fill="${INK}"/>
      <path d="M72 41 q6 -4 12 -2" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${eye(78, 45, 3, eyeInk(c))}
    </g>`,

  // ── Triceratops — parrot beak, nose horn + two big brow horns, huge scalloped neck frill, stocky ──
  triceratops: (c) => `
    <g class="tail-wag"><path d="M32 80 Q16 78 12 88" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M32 80 Q16 78 12 88" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="50" cy="76" rx="28" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M28 82 q22 12 44 0" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 58 : 32}" y="86" width="12" height="18" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="44" y="88" width="11" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <g class="head-tilt">
      <path d="M70 44 Q64 26 80 22 Q98 24 100 44 Q102 62 84 64 Q70 62 70 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1.4" opacity=".55"><path d="M80 24 v6 M90 26 l-2 6 M98 40 l-6 2 M74 34 l6 3"/></g>
      <path d="M78 46 Q78 34 92 34 Q108 36 108 52 Q108 64 96 66 Q82 66 80 56 Q78 52 78 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M104 54 Q110 56 106 64 Q100 64 100 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M100 46 Q102 36 106 42 Q104 46 100 48 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M88 36 Q92 18 100 20 Q98 30 94 40 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M82 38 Q84 22 92 22 Q90 32 88 42 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(90, 50, 2.8, eyeInk(c))}
    </g>`,

  // ── Stegosaurus — arched back with a double row of kite plates, spiked thagomizer tail, tiny head ──
  stegosaurus: (c) => `
    <g class="tail-wag"><path d="M40 78 Q18 76 10 66 Q14 72 20 74 Q30 78 44 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 70 l-6 -8 M15 72 l-6 -3 M22 66 l-3 -9 M26 66 l0 -8" stroke="${IVORY}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M18 70 l-6 -8 M15 72 l-6 -3 M22 66 l-3 -9 M26 66 l0 -8" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round"/></g>
    <g class="breathe"><path d="M30 82 Q30 58 58 54 Q84 54 88 78 Q88 88 60 90 Q34 90 30 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 40}" y="84" width="11" height="18" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="52" y="86" width="10" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <g class="tail-wag">
      ${[[34,64],[46,52],[60,48],[74,52]].map(([x,y]) => `<path d="M${x} ${y+12} Q${x-6} ${y} ${x} ${y-6} Q${x+6} ${y} ${x} ${y+12} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 72 Q86 58 98 58 Q108 60 106 72 Q104 82 94 82 Q86 82 84 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M100 74 Q108 76 104 82 Q98 82 98 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(96, 68, 2.6, eyeInk(c))}
    </g>`,

  // ── Velociraptor — sleek killer, hooked jaws with fangs, grasping arm, deadly foot sickle-claw ────
  velociraptor: (c) => `
    <g class="tail-wag"><path d="M42 66 L4 62 Q14 68 24 69 Q34 71 44 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M52 78 Q48 92 54 98 L60 96 L56 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 72 Q40 56 58 56 Q72 58 74 68 Q74 78 58 80 Q42 80 38 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 74 q14 5 24 0" fill="${c.shade}" opacity=".5"/></g>
    <path d="M56 76 Q50 90 56 98 L62 96 L60 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 98 l6 4 M60 98 l6 2" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <path d="M58 97 Q65 90 73 85 Q67 92 63 99 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M66 66 q8 6 4 12" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
    <path d="M66 66 q8 6 4 12" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
    <path d="M70 78 l3 3 M70 78 l4 1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M68 50 Q72 42 88 42 Q104 42 106 52 Q104 58 92 58 L84 60 Q72 62 68 56 Q66 52 68 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 58 Q96 62 104 58 Q102 64 92 66 Q84 64 86 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M88 56 l1.5 4 l2 -4 M96 55 l1.5 4 l2 -4 M102 54 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <ellipse cx="101" cy="48" rx="1.4" ry="1" fill="${INK}"/>
      <path d="M74 47 q6 -3 12 -1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(80, 50, 2.8, eyeInk(c))}
    </g>`,

  // ── Brachiosaurus — gentle giant, towering long neck, tiny domed head, columnar legs, whip tail ───
  brachiosaurus: (c) => `
    <g class="tail-wag"><path d="M34 84 Q14 82 8 94" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M34 84 Q14 82 8 94" fill="none" stroke="${c.body}" stroke-width="4.4" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="48" cy="82" rx="26" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M26 88 q22 12 44 0" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 56 : 30}" y="88" width="12" height="20" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="44" y="90" width="11" height="18" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <path d="M62 78 Q78 60 78 30" fill="none" stroke="${c.line}" stroke-width="15" stroke-linecap="round"/>
    <path d="M62 78 Q78 60 78 30" fill="none" stroke="${c.body}" stroke-width="11" stroke-linecap="round"/>
    <path d="M70 70 Q80 54 80 34" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".5"/>
    <g class="head-tilt">
      <path d="M74 30 Q74 20 86 20 Q96 22 94 32 Q92 40 82 40 Q76 38 74 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 28 Q68 26 68 32 Q72 34 76 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="72" cy="30" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(84, 28, 2.6, eyeInk(c))}
    </g>`,

  // ── Pterodactyl — spread membrane wings, small head with a back-crest, long tapering beak (float) ─
  pterodactyl: (c) => `
    <g class="tail-wag">
      ${mirror(`<path d="M58 58 Q30 44 12 58 Q26 60 34 66 Q22 66 16 72 Q34 72 44 70 Q52 74 58 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M20 58 q16 4 34 6" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>`)}
      <path d="M58 58 Q30 44 12 58 Q26 60 34 66 Q22 66 16 72 Q34 72 44 70 Q52 74 58 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 58 q16 4 34 6" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
    </g>
    <g class="breathe"><ellipse cx="60" cy="66" rx="10" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 62 q6 8 12 0" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 62 : 58} 80 q${i ? 4 : -4} 6 ${i ? 2 : -2} 12" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <ellipse cx="60" cy="44" rx="9" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 38 Q54 30 50 34 Q56 38 60 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 48 Q58 62 60 66 Q62 62 64 48 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 50 l0 8" stroke="${c.line}" stroke-width="0.9" opacity=".6"/>
      ${eyes(55, 65, 42, 2.4, eyeInk(c))}
    </g>`,

  // ── Ankylosaurus — low armored tank, osteoderm plates & studs, and a heavy bony club tail ─────────
  ankylosaurus: (c) => `
    <g class="tail-wag"><path d="M36 84 Q24 84 18 88" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M36 84 Q24 84 18 88" fill="none" stroke="${c.body}" stroke-width="4.4" stroke-linecap="round"/>
      <circle cx="18" cy="88" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M12 84 l-3 -3 M11 88 l-3 0 M12 92 l-3 3" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/></g>
    <g class="breathe"><path d="M28 82 Q30 62 58 60 Q86 60 90 80 Q90 90 60 92 Q32 92 28 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 38}" y="84" width="12" height="16" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="52" y="86" width="11" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <g>
      <path d="M34 76 q6 -6 12 0 M48 70 q6 -6 12 0 M62 68 q6 -6 12 0 M76 72 q5 -5 10 0" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".55"/>
      ${[[36,72],[50,66],[64,64],[78,68]].map(([x,y]) => `<path d="M${x} ${y+6} L${x-4} ${y} L${x+4} ${y} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 78 Q86 66 98 66 Q108 68 106 80 Q104 88 94 88 Q86 88 84 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M98 68 l4 -3 M104 74 l4 -1" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${eye(94, 76, 2.6, eyeInk(c))}
    </g>`,

  // ── Spinosaurus — towering back sail with fin-rays, long crocodile snout, tiny arm, wading legs ───
  spinosaurus: (c) => `
    <g class="tail-wag"><path d="M38 78 Q16 78 8 92 Q14 92 22 88 Q32 84 44 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M34 74 Q40 34 56 32 Q76 30 82 70 Q70 58 58 56 Q46 56 34 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g stroke="${c.line}" stroke-width="1.4" opacity=".5"><path d="M44 66 Q46 48 50 40 M56 60 V34 M68 62 Q70 48 68 40"/></g>
    <path d="M52 84 Q48 98 54 104 L62 102 L58 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M36 78 Q38 62 58 60 Q80 60 82 76 Q82 86 60 88 Q40 88 36 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 80 q14 5 26 0" fill="${c.shade}" opacity=".45"/></g>
    <path d="M58 82 Q52 98 58 106 L66 104 L64 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 106 l-5 3 M60 106 l1 4 M64 105 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M72 68 q7 5 4 11" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
    <path d="M72 68 q7 5 4 11" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M74 58 Q76 50 96 48 Q110 48 110 56 L96 60 Q84 62 76 64 Q72 62 74 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 62 Q96 66 108 60 Q106 66 94 68 Q84 68 84 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M86 58 l1.5 4 l2 -4 M96 57 l1.5 4 l2 -4 M104 55 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <ellipse cx="104" cy="52" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(82, 55, 2.6, eyeInk(c))}
    </g>`,

  // ── Parasaurolophus — long swept-back tube crest, gentle duck-bill, arched neck, hadrosaur build ──
  parasaurolophus: (c) => `
    <g class="tail-wag"><path d="M40 80 Q18 78 10 90" fill="none" stroke="${c.line}" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M40 80 Q18 78 10 90" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/></g>
    <path d="M50 84 Q46 98 52 104 L60 102 L56 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M36 80 Q40 60 60 58 Q80 58 82 78 Q82 88 58 90 Q40 90 36 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 82 q14 6 26 0" fill="${c.shade}" opacity=".45"/></g>
    <path d="M56 82 Q50 98 56 106 L64 104 L62 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M54 106 l-4 3 M60 106 l4 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M66 74 Q78 60 88 52" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
    <path d="M66 74 Q78 60 88 52" fill="none" stroke="${c.body}" stroke-width="9" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M86 46 Q70 30 52 34 Q56 40 66 42 Q78 46 86 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 37 Q72 40 82 48" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".55"/>
      <path d="M84 44 Q86 36 98 36 Q108 38 108 48 Q108 56 98 58 L90 60 Q84 58 84 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M102 52 Q110 54 106 60 Q100 60 98 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(94, 46, 2.6, eyeInk(c))}
    </g>`,

  // ── Woolly Mammoth — shaggy fur mass, domed head, curling ivory tusks, ridged trunk, little ears ──
  woollymammoth: (c) => `
    <g class="tail-wag"><path d="M32 76 Q20 78 18 88" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M32 76 Q20 78 18 88" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/></g>
    <g class="breathe">
      ${pom(50, 78, 26, c.body, c.line, 16, 2.4)}
      <path d="M30 84 q20 12 40 0" fill="${c.shade}" opacity=".4"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 56 : 36} 92 q0 10 2 14 l8 0 q2 -6 0 -14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`).join("")}
      <g stroke="${c.line}" stroke-width="1.2" opacity=".45"><path d="M34 74 v10 M42 78 v12 M58 78 v12 M66 76 v10"/></g></g>
    <g class="head-tilt">
      ${pom(78, 54, 20, c.body, c.line, 12, 2.4)}
      <path d="M74 40 Q78 32 82 40" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M64 50 Q56 48 58 58 Q64 60 66 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 66 Q80 84 74 94 Q70 100 76 102 Q82 100 82 92 Q86 78 88 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".5"><path d="M79 72 h7 M78 78 h8 M76 86 h7"/></g>
      <path d="M74 70 Q62 82 66 96 Q70 92 70 84 Q74 76 80 72 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M86 70 Q98 82 94 96 Q90 92 90 84 Q86 76 82 72 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(82, 54, 2.8, eyeInk(c))}
    </g>`,

  // ── Sabertooth Tiger — muscular cat, faint stripes, and two enormous curved ivory sabers ─────────
  sabertoothtiger: (c) => `
    <g class="tail-wag"><path d="M84 88 Q106 88 106 68 Q106 60 100 62 Q102 74 92 82 Q86 86 80 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="58" cy="86" rx="25" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 90 q18 11 36 0" fill="${c.shade}" opacity=".55"/>
      <g stroke="${c.line}" stroke-width="2" stroke-linecap="round" opacity=".75"><path d="M46 76 q-1 6 0 12 M58 74 q0 7 0 14 M70 76 q1 6 0 12"/></g>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="94" width="11" height="15" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 30 Q42 20 50 22 Q54 28 52 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M46 30 Q42 20 50 22 Q54 28 52 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="52" rx="22" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 52 Q60 66 74 52 Q74 60 60 62 Q46 60 46 52 Z" fill="${c.shade}"/>
      <g stroke="${c.line}" stroke-width="2" stroke-linecap="round" opacity=".75"><path d="M60 33 v7 M50 36 q-1 5 -2 8 M70 36 q1 5 2 8"/></g>
      <path d="M60 54 L56 59 L64 59 Z" fill="${INK}"/>
      <path d="M54 60 Q52 76 55 84 Q58 78 57 62 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M66 60 Q68 76 65 84 Q62 78 63 62 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(52, 68, 48, 3, eyeInk(c))}
    </g>`,

  // ── Dodo — plump flightless bird, big hooked beak, stubby wing, tuft tail, sturdy yellow legs ─────
  dodo: (c) => `
    <g class="tail-wag"><path d="M30 68 Q14 60 12 70 Q14 76 22 74 Q16 80 18 86 Q28 80 34 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="52" cy="74" rx="24" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 78 q16 12 32 0" fill="${c.shade}" opacity=".45"/>
      <path d="M60 66 Q74 68 70 82 Q62 80 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 56 : 44}" y="94" width="6" height="14" rx="2.4" fill="${HORN}" stroke="${c.line}" stroke-width="2"/><path d="M${i ? 54 : 42} 108 h10" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <ellipse cx="66" cy="44" rx="14" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 40 q6 -3 12 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
      <path d="M76 44 Q94 44 96 54 Q94 62 84 60 Q88 54 80 52 Q76 50 76 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M80 50 q6 0 10 3" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
      ${eye(68, 42, 2.8, eyeInk(c))}
    </g>`,

  // ── Dimetrodon — sprawling low reptile with a tall semicircular spined back sail, croc jaws ───────
  dimetrodon: (c) => `
    <g class="tail-wag"><path d="M34 84 Q16 84 8 90 Q16 92 24 90 Q32 88 40 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M34 84 Q34 44 52 40 Q74 38 82 82 Q72 68 58 66 Q44 66 34 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g stroke="${c.line}" stroke-width="1.6" opacity=".55"><path d="M40 78 Q40 56 46 46 M50 74 V42 M60 72 V40 M70 74 Q72 58 70 46"/></g>
    <g class="breathe"><path d="M32 84 Q34 72 58 70 Q82 70 84 82 Q84 90 58 92 Q36 92 32 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 66 : 40} 90 q${i ? 4 : -4} 8 0 14 l6 0 q2 -6 0 -14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M78 80 Q80 70 96 70 Q108 72 108 80 L96 84 Q86 86 80 86 Q76 84 78 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 84 q10 3 20 0" fill="${c.shade}" opacity=".5"/>
      <path d="M88 82 l1.5 4 l2 -4 M98 81 l1.5 4 l2 -4" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      ${eye(86, 76, 2.6, eyeInk(c))}
    </g>`,

  // ── Pteranodon — gliding profile, huge backward head crest, long toothless beak, tapered wings (float) ─
  pteranodon: (c) => `
    <g class="tail-wag">
      <path d="M56 56 Q30 40 12 48 Q28 54 40 60 Q26 60 18 66 Q36 66 50 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe"><ellipse cx="60" cy="62" rx="16" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 64 q10 6 20 0" fill="${c.shade}" opacity=".45"/></g>
    <g class="tail-wag">
      <path d="M64 58 Q90 42 108 52 Q90 58 78 62 Q92 62 100 68 Q82 68 68 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M70 60 q16 -2 30 -4" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="48" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 44 Q42 34 34 40 Q46 44 56 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M66 46 Q88 44 96 46 Q88 52 68 52 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eye(62, 46, 2.4, eyeInk(c))}
    </g>`,

  // ── Plesiosaur — long serpentine neck, small head, four paddle flippers, rounded body (float) ─────
  plesiosaur: (c) => `
    <g class="tail-wag"><path d="M40 74 Q22 76 12 70" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M40 74 Q22 76 12 70" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="52" cy="72" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M34 76 q18 10 36 0" fill="${c.shade}" opacity=".45"/></g>
    <g class="tail-wag">
      <path d="M42 82 Q34 96 46 96 Q52 90 50 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M62 82 Q56 96 68 94 Q70 88 68 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 66 Q30 54 42 56 Q48 62 46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <path d="M66 64 Q80 48 84 30" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M66 64 Q80 48 84 30" fill="none" stroke="${c.body}" stroke-width="8" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M78 30 Q78 20 90 20 Q100 22 98 32 Q96 40 86 40 Q80 38 78 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M96 30 Q104 30 100 36 Q94 36 94 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      ${eye(88, 28, 2.6, eyeInk(c))}
    </g>`,

  // ── Trilobite — top-down segmented shell, cephalon shield with stalk-set eyes, three axial lobes ──
  trilobite: (c) => `
    <g class="breathe">
      <path d="M60 30 Q86 32 88 64 Q88 92 60 96 Q32 92 32 64 Q34 32 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 46 Q60 34 80 46 Q80 54 60 54 Q40 54 40 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="44" rx="5" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="50" cy="44" r="2.4" fill="${INK}"/><circle cx="70" cy="44" r="2.4" fill="${INK}"/>
      <path d="M50 56 Q48 76 52 90 M70 56 Q72 76 68 90" fill="none" stroke="${c.line}" stroke-width="1.8" opacity=".7"/>
      <g stroke="${c.line}" stroke-width="1.8" opacity=".8"><path d="M36 60 H84 M37 68 H83 M39 76 H81 M43 84 H77"/></g>
      <g stroke="${c.line}" stroke-width="2" stroke-linecap="round"><path d="M34 62 l-4 -1 M35 70 l-4 0 M37 78 l-4 1 M86 62 l4 -1 M85 70 l4 0 M83 78 l4 1"/></g>
    </g>`,

  // ── Allosaurus — agile hunter, paired lacrimal brow crests, toothy grin, three-clawed grasping hand ─
  allosaurus: (c) => `
    <g class="tail-wag"><path d="M40 74 Q16 70 8 82 Q14 84 22 82 Q32 78 46 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M52 80 Q48 94 54 100 L62 98 L58 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 74 Q40 58 58 56 Q76 56 78 70 Q78 80 58 82 Q42 82 38 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 76 q14 5 26 0" fill="${c.shade}" opacity=".45"/></g>
    <path d="M58 78 Q52 94 58 102 L66 100 L64 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 102 l-5 3 M60 102 l1 4 M64 101 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M70 64 q9 5 6 12" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
    <path d="M70 64 q9 5 6 12" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
    <path d="M76 76 l3 3 M76 76 l4 1 M76 76 l1 4" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M66 48 Q70 40 90 40 Q106 40 106 50 L92 54 Q78 56 70 58 Q64 54 66 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M82 56 Q94 60 104 56 Q102 62 90 64 Q80 64 82 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 54 l1.5 4 l2 -4 M94 53 l1.5 4 l2 -4 M102 51 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <path d="M71 46 Q70 33 77 34 Q80 40 78 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M80 45 Q80 31 88 33 Q90 40 86 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <ellipse cx="100" cy="45" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(80, 48, 2.8, eyeInk(c))}
    </g>`,

  // ── Iguanodon — hadrosaur build, arched neck, duck-ish snout, and the trademark ivory thumb spike ─
  iguanodon: (c) => `
    <g class="tail-wag"><path d="M40 82 Q18 80 10 92" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M40 82 Q18 80 10 92" fill="none" stroke="${c.body}" stroke-width="4.4" stroke-linecap="round"/></g>
    <path d="M50 84 Q46 98 52 104 L60 102 L56 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M36 80 Q40 60 60 58 Q80 58 82 78 Q82 88 58 90 Q40 90 36 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 82 q14 6 26 0" fill="${c.shade}" opacity=".45"/></g>
    <path d="M56 82 Q50 98 56 106 L64 104 L62 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M54 106 l-4 3 M60 106 l4 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M68 66 Q78 72 80 82" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
    <path d="M68 66 Q78 72 80 82" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
    <path d="M80 82 l6 -4" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M80 82 l6 -4" stroke="${IVORY}" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M64 72 Q76 60 86 52" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M64 72 Q76 60 86 52" fill="none" stroke="${c.body}" stroke-width="8" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M82 46 Q84 38 98 38 Q108 40 108 50 Q108 58 98 60 L90 62 Q82 60 82 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M102 54 Q110 56 105 62 Q99 62 98 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(92, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Compsognathus — dainty chicken-sized sprinter, whippy neck & tail, nimble legs, tiny toothy jaw ─
  compsognathus: (c) => `
    <g class="tail-wag"><path d="M46 66 Q24 58 10 64 Q22 66 32 68 Q22 72 16 78 Q34 74 48 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <path d="M52 74 Q50 88 54 96 L60 94 L56 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    <g class="breathe"><ellipse cx="52" cy="68" rx="15" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 72 q10 6 20 0" fill="${c.shade}" opacity=".45"/></g>
    <path d="M56 74 Q52 90 58 98 L64 96 L62 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 98 l-4 3 M60 98 l3 4" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    <path d="M60 62 q6 4 4 9" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M60 62 q6 4 4 9" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
    <path d="M58 62 Q68 50 76 44" fill="none" stroke="${c.line}" stroke-width="9" stroke-linecap="round"/>
    <path d="M58 62 Q68 50 76 44" fill="none" stroke="${c.body}" stroke-width="5.6" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M72 40 Q74 32 86 32 Q98 34 98 42 L88 46 Q78 48 74 46 Q70 44 72 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 44 l1 3 l1.5 -3 M94 42 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      <ellipse cx="94" cy="38" rx="1.2" ry="0.9" fill="${INK}"/>
      ${eye(80, 39, 2.4, eyeInk(c))}
    </g>`,

  // ── Archaeopteryx — feathered dino-bird, spread clawed wing, long feathered bony tail, toothed beak (float) ─
  archaeopteryx: (c) => `
    <g class="tail-wag">
      <path d="M40 70 Q20 74 8 72 Q18 78 8 84 Q22 82 32 78 Q28 84 22 88 Q38 82 46 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 72 q-14 3 -26 2" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".55"/>
    </g>
    <g class="breathe"><ellipse cx="56" cy="66" rx="16" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 70 q10 6 20 0" fill="${c.shade}" opacity=".45"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 62 : 52} 76 q${i ? 2 : -2} 8 0 12" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><path d="M${i ? 62 : 52} 88 l-3 3 M${i ? 62 : 52} 88 l3 3" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>`).join("")}</g>
    <g class="tail-wag">
      <path d="M62 58 Q84 40 106 46 Q92 52 78 56 Q94 56 104 62 Q86 64 70 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".55"><path d="M72 54 l16 -6 M76 58 l18 -2 M74 60 l16 2"/></g>
      <path d="M104 46 l4 -3" stroke="${IVORY}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M104 46 l4 -3" stroke="${c.line}" stroke-width="1" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="62" cy="50" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M68 50 Q80 48 84 52 Q80 56 68 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 53 l1 2 M78 53 l1 2" stroke="${c.line}" stroke-width="0.8"/>
      <path d="M58 44 q4 -6 8 -3" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${eye(64, 48, 2.4, eyeInk(c))}
    </g>`,
};

export const ROSTER_DINOS = [
  { n: "Tyrannosaurus",  e: "🦖", tier: 5, float: false },
  { n: "Triceratops",    e: "🦕", tier: 4, float: false },
  { n: "Stegosaurus",    e: "🦕", tier: 4, float: false },
  { n: "Velociraptor",   e: "🦖", tier: 4, float: false },
  { n: "Brachiosaurus",  e: "🦕", tier: 4, float: false },
  { n: "Pterodactyl",    e: "🐉", tier: 3, float: true  },
  { n: "Ankylosaurus",   e: "🦕", tier: 3, float: false },
  { n: "Spinosaurus",    e: "🦖", tier: 5, float: false },
  { n: "Parasaurolophus", e: "🦕", tier: 3, float: false },
  { n: "Woolly Mammoth", e: "🦣", tier: 4, float: false },
  { n: "Sabertooth Tiger", e: "🐅", tier: 4, float: false },
  { n: "Dodo",           e: "🦤", tier: 2, float: false },
  { n: "Dimetrodon",     e: "🦎", tier: 3, float: false },
  { n: "Pteranodon",     e: "🦕", tier: 3, float: true  },
  { n: "Plesiosaur",     e: "🦕", tier: 3, float: true  },
  { n: "Trilobite",      e: "🐛", tier: 2, float: false },
  { n: "Allosaurus",     e: "🦖", tier: 4, float: false },
  { n: "Iguanodon",      e: "🦕", tier: 3, float: false },
  { n: "Compsognathus",  e: "🦎", tier: 2, float: false },
  { n: "Archaeopteryx",  e: "🪶", tier: 3, float: true  },
];
