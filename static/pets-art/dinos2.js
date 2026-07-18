// pets-art/dinos2.js — BESPOKE hand-drawn SVG art for the DINOS2 batch (more dinosaurs & marine
// reptiles, distinct from dinos.js). Each entry: slug -> (c) => "<svg inner markup>" for
// <svg viewBox="0 0 120 120">. Palette-driven: c.body (main fill) · c.shade (sail/underside/armor/
// crest) · c.line (outline). Teeth/claws use #fff or warm ivory; nose/eye = INK/eyeInk. Torso in
// .breathe, head/face in .head-tilt, tails/wings/flippers in .tail-wag. Fliers/swimmers set
// float:true and are drawn horizontally, facing right. Keys are name-slugs matching ROSTER_DINOS2.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const IVORY = "#f4efe2";  // big claws / horns / tusks / sabers
const HORN  = "#d9c9a3";  // beaks / bills / casques
const TEETH = "#ffffff";

export const ART_DINOS2 = {
  // ── Carnotaurus — deep short bulldog snout, two thick bull horns OVER the eyes, absurdly tiny arms ──
  carnotaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M42 74 Q16 68 6 80 Q12 84 20 82 Q32 76 48 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 78 q12 -3 24 -2" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".55"/></g>
    <path d="M52 82 Q48 96 54 102 L62 100 L58 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 76 Q40 58 60 56 Q80 56 82 72 Q82 82 60 84 Q42 84 38 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="78" rx="18" ry="7" fill="${B}" opacity=".7"/></g>
    <path d="M58 80 Q52 96 58 104 L66 102 L64 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 104 l-5 3 M60 104 l1 4 M64 103 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M70 66 q5 3 3 8" fill="none" stroke="${c.line}" stroke-width="3.2" stroke-linecap="round"/>
    <path d="M70 66 q5 3 3 8" fill="none" stroke="${c.body}" stroke-width="1.8" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M66 52 Q68 42 88 42 Q104 44 104 55 L92 59 Q76 60 70 60 Q64 57 66 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 58 Q92 62 102 58 Q100 64 88 66 Q80 66 80 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 58 l1.5 4 l2 -4 M94 57 l1.5 4 l2 -4 M100 55 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <path d="M74 45 Q70 33 79 33 Q80 39 80 47 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M82 44 Q82 32 91 34 Q88 40 86 47 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="99" cy="50" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(82, 52, 2.8, eyeInk(c))}
    </g>`; },

  // ── Baryonyx — long slender crocodile snout, conical teeth, and one huge hooked thumb claw ─────────
  baryonyx: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 78 Q16 74 6 86 Q12 90 20 88 Q32 82 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M52 82 Q48 96 54 102 L62 100 L58 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M44 74 Q56 46 72 50 Q82 53 82 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 66 Q58 54 63 50 M66 66 Q68 54 73 51" fill="none" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      <path d="M36 78 Q38 60 58 58 Q80 58 82 76 Q82 86 58 88 Q40 88 36 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="58" cy="80" rx="18" ry="7" fill="${B}" opacity=".7"/></g>
    <path d="M58 82 Q52 98 58 106 L66 104 L64 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 106 l-5 3 M60 106 l1 4 M64 105 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M70 66 Q80 74 82 84" fill="none" stroke="${c.line}" stroke-width="4.5" stroke-linecap="round"/>
      <path d="M70 66 Q80 74 82 84" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M82 84 Q96 86 100 101 Q101 105 97 104 Q93 97 84 92 Q80 88 82 84 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M68 54 Q70 48 104 46 Q112 46 112 52 L98 56 Q78 60 72 60 Q66 58 68 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 58 Q96 62 110 55 Q108 62 94 66 Q80 66 80 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 58 l1.4 4 l1.8 -4 M92 57 l1.4 4 l1.8 -4 M100 55 l1.2 4 l1.6 -4 M106 53 l1 3 l1.4 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      <ellipse cx="106" cy="50" rx="1.3" ry="0.9" fill="${INK}"/>
      ${eye(80, 53, 2.6, eyeInk(c))}
    </g>`; },

  // ── Giganotosaurus — colossal carcharodont, massive deep head, bony brow ridge, muscular tail ──────
  giganotosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 72 Q12 66 4 80 Q10 84 18 82 Q32 74 46 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M18 78 q12 -3 26 -2" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".55"/></g>
    <path d="M52 82 Q48 98 54 106 L64 104 L58 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="breathe"><path d="M34 76 Q36 54 60 52 Q84 52 86 74 Q86 86 60 88 Q38 88 34 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="79" rx="20" ry="8" fill="${B}" opacity=".7"/></g>
    <path d="M60 82 Q54 100 60 108 L70 106 L66 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M58 108 l-6 3 M62 108 l1 4 M67 107 l6 3" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    <path d="M74 64 q7 4 5 11" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
    <path d="M74 64 q7 4 5 11" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
    <path d="M79 75 l3 3 M79 75 l4 1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M64 42 Q68 30 92 30 Q110 32 110 46 L94 50 Q74 54 68 54 Q60 50 64 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M80 52 Q96 58 108 52 Q106 60 92 62 Q80 62 80 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 51 l1.6 5 l2 -5 M94 50 l1.6 5 l2 -5 M103 49 l1.4 4 l1.8 -4" fill="${TEETH}" stroke="${c.line}" stroke-width="1"/>
      <path d="M70 40 Q78 34 92 36" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".7"/>
      <ellipse cx="104" cy="41" rx="1.6" ry="1.1" fill="${INK}"/>
      ${eye(80, 43, 3, eyeInk(c))}
    </g>`; },

  // ── Deinonychus — feathered raptor, tuft on the arm, one foot raised showing the killer sickle claw ─
  deinonychus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 66 Q16 60 6 68 Q12 72 22 70 Q34 68 46 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".5"><path d="M18 66 l-4 -4 M26 66 l-3 -5 M34 68 l-2 -5"/></g></g>
    <path d="M52 76 Q48 90 54 96 L60 94 L56 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 72 Q40 56 58 56 Q74 58 76 68 Q76 78 58 80 Q42 80 38 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="58" cy="73" rx="15" ry="6" fill="${B}" opacity=".7"/></g>
    <path d="M56 78 Q50 92 56 100 L62 98 L60 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M52 99 Q41 100 36 93 Q40 100 47 103 Q51 103 52 99 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
    <path d="M56 100 l6 3 M60 100 l5 2" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M64 64 q9 4 8 12" fill="none" stroke="${c.line}" stroke-width="3.8" stroke-linecap="round"/>
      <path d="M64 64 q9 4 8 12" fill="none" stroke="${c.body}" stroke-width="2.2" stroke-linecap="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".5"><path d="M66 60 l6 -3 M70 62 l6 -2 M72 66 l6 0"/></g>
      <path d="M72 76 l3 3 M72 76 l4 1" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M66 50 Q70 42 88 42 Q104 42 106 52 Q104 58 92 58 L84 60 Q72 62 68 56 Q64 52 66 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 58 Q96 62 104 58 Q102 64 92 66 Q84 64 86 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M88 56 l1.5 4 l2 -4 M96 55 l1.5 4 l2 -4 M102 54 l1 3 l1.5 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <path d="M70 44 Q72 37 78 39 Q77 43 78 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="101" cy="48" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(82, 50, 2.8, eyeInk(c))}
    </g>`; },

  // ── Utahraptor — big bulky raptor, feathered crest & tail, oversized foot sickle claw ──────────────
  utahraptor: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 68 Q14 62 4 70 Q10 74 22 72 Q34 70 46 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1.1" opacity=".5"><path d="M16 68 l-5 -5 M25 68 l-4 -6 M34 70 l-3 -6"/></g></g>
    <path d="M52 80 Q48 96 54 102 L62 100 L58 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="breathe"><path d="M36 74 Q38 56 60 54 Q80 56 82 70 Q82 82 60 84 Q40 84 36 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="59" cy="76" rx="18" ry="7" fill="${B}" opacity=".7"/></g>
    <path d="M60 82 Q54 98 60 106 L68 104 L64 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M55 102 l6 3 M59 101 l5 2" stroke="${c.line}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <path d="M60 106 l6 3 M64 106 l5 2" stroke="${c.line}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <path d="M72 62 q9 5 6 12" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
    <path d="M72 62 q9 5 6 12" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
    <path d="M78 74 l3 3 M78 74 l4 1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M64 48 Q68 40 88 40 Q106 40 108 51 Q106 58 92 58 L84 60 Q70 62 66 56 Q62 51 64 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M84 58 Q96 62 106 58 Q104 64 92 66 Q82 64 84 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M86 56 l1.6 5 l2 -5 M95 55 l1.6 5 l2 -5 M103 54 l1.2 4 l1.6 -4" fill="${TEETH}" stroke="${c.line}" stroke-width="0.9"/>
      <path d="M66 42 Q66 32 74 34 Q73 39 74 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M73 40 Q74 31 82 34 Q80 40 80 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="103" cy="47" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(82, 49, 2.9, eyeInk(c))}
    </g>`; },

  // ── Microraptor — tiny four-winged glider: feathered arm-wings AND leg-wings, feathered tail (float) ─
  microraptor: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M46 64 Q22 58 6 62 Q18 66 30 66 Q20 70 12 74 Q30 70 46 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="0.9" opacity=".5"><path d="M20 62 l0 4 M28 63 l0 4 M36 64 l0 4"/></g>
    </g>
    <g class="tail-wag">
      <path d="M56 58 Q34 40 16 42 Q30 48 42 54 Q28 52 20 56 Q38 60 54 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 56 Q36 42 22 40 Q34 47 46 52 Q34 52 26 56 Q42 58 54 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="0.9" opacity=".5"><path d="M30 46 l12 7 M26 51 l14 5"/></g>
    </g>
    <g class="tail-wag">
      <path d="M56 72 Q34 86 18 86 Q32 80 44 76 Q32 82 26 88 Q44 82 54 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 74 Q38 84 24 86 Q36 80 48 78 Q40 82 34 88 Q48 82 55 79 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="0.9" opacity=".5"><path d="M32 80 l14 -5 M30 84 l16 -6"/></g>
    </g>
    <g class="breathe"><ellipse cx="60" cy="64" rx="14" ry="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="66" rx="9" ry="5" fill="${B}" opacity=".7"/></g>
    <g class="head-tilt">
      <ellipse cx="76" cy="56" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M82 55 Q94 53 98 57 Q94 61 82 60 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M87 57 l1 2 M91 56 l1 2" stroke="${c.line}" stroke-width="0.8"/>
      <path d="M72 49 Q73 42 78 44 Q77 48 78 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(78, 54, 2.6, eyeInk(c))}
    </g>`; },

  // ── Therizinosaurus — pot-bellied, long neck, tiny head, and monstrous curved scythe hand-claws ────
  therizinosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M46 84 Q26 86 14 94" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M46 84 Q26 86 14 94" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/></g>
    <path d="M48 88 Q44 102 50 108 L58 106 L54 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 74 Q36 52 60 50 Q86 50 86 78 Q86 96 60 98 Q40 98 38 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="19" ry="12" fill="${B}" opacity=".75"/></g>
    <path d="M58 90 Q52 104 58 110 L66 108 L64 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 110 l-4 2 M60 110 l1 3 M64 109 l5 2" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M74 66 Q84 72 87 82" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M74 66 Q84 72 87 82" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
      ${[0,1,2].map(k=>`<path d="M${85+k*2.5} 82 Q${99+k*4} 90 ${92+k*4} 104" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M${85+k*2.5} 82 Q${99+k*4} 90 ${92+k*4} 104" fill="none" stroke="${IVORY}" stroke-width="1.8" stroke-linecap="round"/>`).join("")}
    </g>
    <path d="M66 56 Q76 44 84 34" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M66 56 Q76 44 84 34" fill="none" stroke="${c.body}" stroke-width="6.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M78 34 Q78 24 90 24 Q100 26 98 36 Q96 42 88 42 Q80 40 78 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 32 Q70 30 70 36 Q75 38 80 35 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(88, 32, 2.4, eyeInk(c))}
    </g>`; },

  // ── Pachycephalosaurus — thick bony domed skull ringed with knobs, blunt snout, bipedal ────────────
  pachycephalosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M42 80 Q20 78 10 90" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M42 80 Q20 78 10 90" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/></g>
    <path d="M50 82 Q46 96 52 102 L60 100 L56 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 78 Q40 58 60 56 Q82 56 84 78 Q84 88 60 90 Q42 90 38 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="18" ry="7" fill="${B}" opacity=".7"/></g>
    <path d="M58 82 Q52 98 58 104 L66 102 L64 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 104 l-4 3 M60 104 l1 4 M64 103 l5 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M72 66 q6 4 4 10" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M72 66 q6 4 4 10" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M70 54 Q72 46 92 46 Q104 48 104 57 Q100 63 88 63 Q74 63 70 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M68 50 Q72 30 90 32 Q104 34 102 52 Q88 47 78 49 Q72 51 68 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 40 q8 -5 16 -2" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      ${[[71,50],[76,45],[98,50],[103,55]].map(([x,y])=>`<circle cx="${x}" cy="${y}" r="1.7" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3"/>`).join("")}
      <ellipse cx="101" cy="55" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(84, 56, 2.8, eyeInk(c))}
    </g>`; },

  // ── Protoceratops — sheep-sized ceratopsian, modest neck frill, parrot beak, four stubby legs ──────
  protoceratops: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M32 82 Q16 82 8 90" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M32 82 Q16 82 8 90" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="48" cy="78" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="48" cy="82" rx="19" ry="7" fill="${B}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 54 : 30}" y="86" width="11" height="16" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="42" y="88" width="10" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <path d="M60 70 Q72 58 84 55 Q90 60 87 67 Q75 76 62 75 Z" fill="${c.body}"/>
    <path d="M66 66 Q76 59 84 56" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M72 48 Q66 30 84 26 Q102 28 104 48 Q106 64 88 66 Q74 64 72 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1.3" opacity=".5"><path d="M84 30 v8 M94 32 l-2 8 M76 38 l7 3"/></g>
      <path d="M78 52 Q80 42 94 42 Q108 44 108 58 Q108 70 96 72 Q82 72 80 62 Q78 58 78 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M104 58 Q112 60 108 68 Q101 68 100 62 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(92, 54, 2.7, eyeInk(c))}
    </g>`; },

  // ── Gallimimus — slender ostrich-mimic, whip neck, small toothless beak, very long running legs ────
  gallimimus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M42 66 Q18 60 6 66 Q16 70 28 70 Q18 74 10 80 Q30 74 46 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M50 74 Q44 92 48 102 L56 100 L54 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <path d="M48 100 l-4 4 M48 100 l4 4" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <g class="breathe"><ellipse cx="52" cy="66" rx="16" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="52" cy="69" rx="11" ry="5" fill="${B}" opacity=".7"/></g>
    <path d="M56 74 Q52 92 56 102 L64 100 L62 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 102 l-4 4 M60 102 l4 4" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M60 60 q7 3 5 9" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
    <path d="M60 60 q7 3 5 9" fill="none" stroke="${c.body}" stroke-width="1.8" stroke-linecap="round"/>
    <path d="M60 58 Q70 44 78 36" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
    <path d="M60 58 Q70 44 78 36" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
    <g class="head-tilt">
      <ellipse cx="80" cy="34" rx="9" ry="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M86 34 Q98 33 102 37 Q98 41 86 40 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="97" cy="35" rx="1.1" ry="0.8" fill="${INK}"/>
      ${eye(80, 32, 2.5, eyeInk(c))}
    </g>`; },

  // ── Oviraptor — tall bony head-casque, deep toothless parrot beak, feathered arms & tail ───────────
  oviraptor: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M42 70 Q18 66 6 74 Q14 78 26 76 Q36 74 46 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".5"><path d="M18 72 l0 5 M26 72 l0 5 M34 74 l0 5"/></g></g>
    <path d="M50 78 Q46 92 50 100 L58 98 L56 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><ellipse cx="54" cy="70" rx="17" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="54" cy="73" rx="11" ry="5" fill="${B}" opacity=".7"/></g>
    <path d="M56 78 Q52 94 56 102 L64 100 L62 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 102 l-4 4 M60 102 l4 4" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M64 64 q9 3 8 11" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M64 64 q9 3 8 11" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".5"><path d="M66 60 l6 -2 M70 62 l6 -1"/></g>
    </g>
    <path d="M62 58 Q70 48 76 42" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
    <path d="M62 58 Q70 48 76 42" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
    <g class="head-tilt">
      <ellipse cx="82" cy="40" rx="10" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M78 32 Q80 20 90 22 Q96 28 90 36 Q86 32 80 34 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M88 40 Q100 38 102 43 Q100 48 88 47 Q84 44 88 40 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M88 43 q6 0 11 1" fill="none" stroke="${c.line}" stroke-width="1" opacity=".55"/>
      ${eye(84, 39, 2.7, eyeInk(c))}
    </g>`; },

  // ── Diplodocus — colossal low sauropod, near-horizontal neck, and an enormously long whip tail ─────
  diplodocus: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M40 78 Q22 82 8 76" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M40 78 Q22 82 8 76" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
      <path d="M14 78 Q8 80 4 74" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
      <path d="M14 78 Q8 80 4 74" fill="none" stroke="${c.body}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="breathe"><ellipse cx="50" cy="76" rx="26" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="50" cy="80" rx="20" ry="7" fill="${B}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 56 : 32}" y="84" width="12" height="22" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="44" y="86" width="11" height="20" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <path d="M64 70 Q82 62 100 48" fill="none" stroke="${c.line}" stroke-width="11" stroke-linecap="round"/>
    <path d="M64 70 Q82 62 100 48" fill="none" stroke="${c.body}" stroke-width="7.5" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M94 44 Q94 34 106 34 Q114 36 112 46 Q110 52 102 52 Q96 50 94 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M110 42 Q116 42 113 48 Q107 48 107 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      ${eye(101, 42, 2.5, eyeInk(c))}
    </g>`; },

  // ── Kentrosaurus — plates up front, long paired spikes down the back & tail, jutting shoulder spikes ─
  kentrosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 78 Q18 76 8 66 Q14 72 20 74 Q30 78 44 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 74 l-8 -6 M17 76 l-8 -2 M24 72 l-4 -8" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round"/>
      <path d="M20 74 l-7 -5 M17 76 l-7 -2 M24 72 l-3 -7" stroke="${IVORY}" stroke-width="2.8" stroke-linecap="round"/></g>
    <g class="breathe"><path d="M30 82 Q30 60 58 56 Q84 56 88 78 Q88 88 60 90 Q34 90 30 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="58" cy="82" rx="20" ry="7" fill="${B}" opacity=".65"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 40}" y="84" width="11" height="18" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="52" y="86" width="10" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <g class="tail-wag">
      ${[[38,60],[50,52],[62,50]].map(([x,y]) => `<path d="M${x-4} ${y+10} L${x} ${y-8} L${x+4} ${y+10} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`).join("")}
      <path d="M74 60 L84 44" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/>
      <path d="M74 60 L84 44" stroke="${IVORY}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M80 66 L94 56" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M80 66 L94 56" stroke="${IVORY}" stroke-width="2.2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 74 Q86 60 98 60 Q108 62 106 74 Q104 84 94 84 Q86 84 84 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M100 76 Q108 78 104 84 Q98 84 98 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(96, 70, 2.6, eyeInk(c))}
    </g>`; },

  // ── Styracosaurus — massive nose horn and a frill crowned with a fan of long straight spikes ───────
  styracosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M30 82 Q16 82 8 90" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M30 82 Q16 82 8 90" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="46" cy="80" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="46" cy="84" rx="19" ry="7" fill="${B}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 52 : 28}" y="88" width="11" height="16" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <rect x="40" y="90" width="10" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/></g>
    <path d="M58 72 Q70 59 82 56 Q88 61 85 68 Q73 77 60 76 Z" fill="${c.body}"/>
    <path d="M64 68 Q74 60 83 57" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <g>${[[70,30],[70,40],[74,22],[82,18],[90,20]].map(([x,y]) => `<path d="M${x} ${y+8} L${x-2} ${y-8} L${x+3} ${y+7} Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}</g>
      <path d="M70 46 Q66 30 82 28 Q98 30 98 48 Q98 62 84 64 Q72 62 70 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 52 Q82 42 96 42 Q110 44 110 58 Q110 70 98 72 Q84 72 82 62 Q80 58 80 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M106 56 Q114 58 110 66 Q103 66 102 60 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M100 48 Q102 30 110 32 Q108 42 106 52 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eye(92, 54, 2.7, eyeInk(c))}
    </g>`; },

  // ── Dilophosaurus — twin thin head crests and a spread ruffled neck frill, slim toothy jaws ────────
  dilophosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M40 72 Q16 66 6 76 Q12 80 22 78 Q34 74 46 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <path d="M52 80 Q48 94 54 100 L60 98 L56 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M38 74 Q40 58 58 56 Q76 56 78 70 Q78 80 58 82 Q42 82 38 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="58" cy="76" rx="16" ry="6" fill="${B}" opacity=".7"/></g>
    <path d="M56 80 Q50 96 56 104 L62 102 L60 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 104 l-4 3 M60 104 l1 4 M64 103 l4 3" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    <path d="M66 64 q7 4 5 10" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M66 64 q7 4 5 10" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M72 54 Q60 44 58 60 Q66 54 74 58 Q64 58 62 70 Q72 60 80 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M68 50 Q72 42 90 42 Q104 42 104 52 L92 56 Q76 58 70 58 Q64 54 68 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 56 Q92 60 102 56 Q100 62 88 64 Q80 64 80 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 56 l1.4 4 l1.8 -4 M92 55 l1.4 4 l1.8 -4 M100 53 l1 3 l1.4 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      <path d="M74 43 Q72 30 82 30 Q80 38 80 45 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M82 43 Q82 29 92 31 Q88 38 88 45 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="99" cy="48" rx="1.3" ry="0.9" fill="${INK}"/>
      ${eye(82, 50, 2.7, eyeInk(c))}
    </g>`; },

  // ── Coelophysis — dainty, ultra-slender early theropod, whippy S-neck & tail, narrow toothy snout ──
  coelophysis: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M46 68 Q22 60 6 64 Q20 66 30 68 Q20 72 12 78 Q32 72 48 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <path d="M52 74 Q50 88 54 96 L60 94 L56 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    <path d="M52 96 l-4 4 M56 96 l3 4" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    <g class="breathe"><ellipse cx="52" cy="66" rx="14" ry="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="52" cy="69" rx="9" ry="4" fill="${B}" opacity=".7"/></g>
    <path d="M56 72 Q52 88 58 96 L64 94 L62 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M56 96 l-3 4 M60 96 l3 4" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    <path d="M60 60 q6 3 4 8" fill="none" stroke="${c.line}" stroke-width="2.8" stroke-linecap="round"/>
    <path d="M60 60 q6 3 4 8" fill="none" stroke="${c.body}" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M58 58 Q66 46 74 40" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
    <path d="M58 58 Q66 46 74 40" fill="none" stroke="${c.body}" stroke-width="4.2" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M70 38 Q72 31 88 31 Q100 33 100 40 L90 44 Q78 46 74 44 Q68 42 70 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M86 42 l1 3 l1.4 -3 M92 41 l1 3 l1.4 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.7"/>
      <ellipse cx="95" cy="37" rx="1.1" ry="0.8" fill="${INK}"/>
      ${eye(80, 37, 2.4, eyeInk(c))}
    </g>`; },

  // ── Quetzalcoatlus — giraffe-necked giant pterosaur, spear beak, tall crest, vast wings (float) ────
  quetzalcoatlus: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M52 60 Q28 42 8 48 Q24 54 36 60 Q22 60 12 66 Q32 66 48 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M22 52 q16 5 30 6" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>
    </g>
    <g class="breathe"><ellipse cx="56" cy="66" rx="13" ry="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="56" cy="69" rx="8" ry="4" fill="${B}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 60 : 52} 76 q${i ? 3 : -3} 6 ${i ? 1 : -1} 11" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>`).join("")}</g>
    <g class="tail-wag">
      <path d="M62 60 Q86 44 108 52 Q90 56 76 60 Q92 60 102 66 Q84 66 66 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M70 58 q16 -2 32 -3" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>
    </g>
    <path d="M62 60 Q72 48 76 36" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
    <path d="M62 60 Q72 48 76 36" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
    <g class="head-tilt">
      <ellipse cx="78" cy="34" rx="8" ry="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M76 28 Q72 14 82 14 Q86 22 82 30 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M84 33 Q104 30 112 34 Q104 40 84 38 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eye(80, 33, 2.5, eyeInk(c))}
    </g>`; },

  // ── Mosasaurus — huge marine lizard, gator jaws with fangs, four paddle flippers, finned tail (float) ─
  mosasaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M40 64 L14 46 Q8 56 10 66 Q8 76 16 84 L40 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M14 46 Q22 56 22 64" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".55"/>
    </g>
    <g class="breathe"><path d="M32 64 Q34 48 64 48 Q94 50 104 64 Q94 80 64 82 Q36 80 32 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 70 Q66 82 96 70 Q68 78 40 70 Z" fill="${B}" opacity=".7"/></g>
    <g class="tail-wag">
      <path d="M46 78 Q40 94 54 94 Q58 86 56 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M68 80 Q64 96 78 92 Q78 84 76 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 58 Q34 46 46 48 Q52 54 50 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M92 54 Q94 48 110 48 Q116 48 116 54 L104 58 Q94 62 90 60 Q88 58 92 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M92 60 Q104 66 114 58 Q112 66 100 68 Q90 68 90 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M96 58 l1.4 4 l1.8 -4 M104 57 l1.4 4 l1.8 -4 M111 55 l1 3 l1.4 -3" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      <ellipse cx="110" cy="52" rx="1.3" ry="0.9" fill="${INK}"/>
      ${eye(96, 54, 2.5, eyeInk(c))}
    </g>`; },

  // ── Elasmosaurus — small round body, four paddles, and an impossibly long swan neck (float) ────────
  elasmosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M42 76 Q26 80 14 74" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M42 76 Q26 80 14 74" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="50" cy="74" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M34 78 Q50 88 68 78 Q50 84 34 78 Z" fill="${B}" opacity=".7"/></g>
    <g class="tail-wag">
      <path d="M42 82 Q34 96 48 94 Q52 88 50 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 82 Q56 96 70 92 Q70 86 68 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 66 Q30 54 42 56 Q48 62 46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <path d="M62 68 Q84 62 88 40 Q90 24 78 20" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
    <path d="M62 68 Q84 62 88 40 Q90 24 78 20" fill="none" stroke="${c.body}" stroke-width="6.4" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M78 24 Q72 14 82 12 Q92 14 92 24 Q92 32 82 32 Q76 30 78 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M76 22 Q68 20 70 26 Q75 28 79 25 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eye(85, 22, 2.5, eyeInk(c))}
    </g>`; },

  // ── Megalodon — monstrous shark, gaping toothy maw, tall dorsal fin, crescent tail, pectoral fins (float) ─
  megalodon: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M38 62 L12 44 Q16 62 12 82 L38 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M18 52 q6 10 4 22" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".55"/>
    </g>
    <path d="M60 40 L72 16 L80 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    <g class="tail-wag">
      <path d="M56 74 L54 96 L74 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe"><path d="M34 62 Q38 40 74 40 Q102 42 112 60 Q104 74 92 76 Q60 84 34 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 68 Q70 82 100 70 Q68 80 40 68 Z" fill="${B}" opacity=".75"/>
      <g stroke="${c.line}" stroke-width="1.3" opacity=".5"><path d="M86 50 l3 8 M92 50 l3 9 M98 52 l3 8"/></g></g>
    <g class="head-tilt">
      <path d="M96 58 Q106 60 112 60 Q108 70 96 72 Q92 66 96 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M97 60 l2 5 l2 -5 M104 60 l2 5 l2 -5 M110 60 l1.6 4 l1.8 -4" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      <path d="M96 64 l2 -4 l2 4 M103 64 l2 -4 l2 4" fill="${TEETH}" stroke="${c.line}" stroke-width="0.8"/>
      ${eye(90, 55, 2.6, eyeInk(c))}
    </g>`; },
};

export const ROSTER_DINOS2 = [
  { n: "Carnotaurus",       e: "🦖", tier: 4, float: false },
  { n: "Baryonyx",          e: "🦖", tier: 3, float: false },
  { n: "Giganotosaurus",    e: "🦖", tier: 5, float: false },
  { n: "Deinonychus",       e: "🦖", tier: 3, float: false },
  { n: "Utahraptor",        e: "🦖", tier: 4, float: false },
  { n: "Microraptor",       e: "🪶", tier: 3, float: true  },
  { n: "Therizinosaurus",   e: "🦕", tier: 4, float: false },
  { n: "Pachycephalosaurus", e: "🦕", tier: 3, float: false },
  { n: "Protoceratops",     e: "🦕", tier: 2, float: false },
  { n: "Gallimimus",        e: "🦖", tier: 2, float: false },
  { n: "Oviraptor",         e: "🦖", tier: 2, float: false },
  { n: "Diplodocus",        e: "🦕", tier: 4, float: false },
  { n: "Kentrosaurus",      e: "🦕", tier: 3, float: false },
  { n: "Styracosaurus",     e: "🦕", tier: 3, float: false },
  { n: "Dilophosaurus",     e: "🦖", tier: 3, float: false },
  { n: "Coelophysis",       e: "🦖", tier: 2, float: false },
  { n: "Quetzalcoatlus",    e: "🐉", tier: 4, float: true  },
  { n: "Mosasaurus",        e: "🦈", tier: 4, float: true  },
  { n: "Elasmosaurus",      e: "🦕", tier: 4, float: true  },
  { n: "Megalodon",         e: "🦈", tier: 5, float: true  },
];
