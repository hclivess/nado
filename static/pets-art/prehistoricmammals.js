// pets-art/prehistoricmammals.js — BESPOKE hand-drawn SVG art for ICE-AGE & ANCIENT MAMMALS (NADO Pets).
// Each entry: slug -> (c) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,64),
// within x,y ∈ [8,114]. Palette-driven: c.body (main fill) · c.shade (darker accent/underside) ·
// c.line (outline). Tusks/horns/claws use fixed warm ivory; body tones derive from `c` via belly/tint/deepen.
// HOUSE STYLE: one bulky body silhouette + legs/head/horns overlapping so NOTHING floats, a pale belly
// two-tone patch, and a clean cute face. Torso in .breathe, head in .head-tilt, tails/appendages in .tail-wag.
// Signatures kept DISTINCT: woollyrhino = shaggy + two in-line nose horns; glyptodon = smooth dome + round
// club; doedicurus = dome + SPIKED mace tail; groundsloth = upright big claws; direwolf = robust canid;
// cavebear = massive low bear; andrewsarchus = long toothy skull + hooves; entelodont = hell-pig cheek knobs;
// chalicothere = horse head + knuckle-walk claws; uintatherium = six head knobs + sabers; basilosaurus = float
// whale + tiny legs; irishelk = giant palmate antlers; paraceratherium = long-neck giant; macrauchenia = trunk-
// nose llama; thylacine = striped marsupial wolf; diprotodon = giant wombat; shortfacedbear = tall long legs;
// aurochs = wild ox horns; gigantopithecus = giant ape; arsinoitherium = twin nose horns. Keys == ROSTER `n`.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const IVORY = "#f0e6d2";   // tusks / horns / big claws
const HORNSH = "#d9c9a3";  // shaded ivory
const HOOF = "#3a2f26";    // hoof / claw tips

// two side-profile legs (front + back) tucked under a torso — overlap the belly so no seam shows
const legs = (c, xl, xr, y, w, h, foot) => ["", "s"].map((_, i) =>
  `<rect x="${i ? xr : xl}" y="${y}" width="${w}" height="${h}" rx="${(w / 2.6).toFixed(1)}" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>` +
  (foot ? `<rect x="${(i ? xr : xl) - 1}" y="${y + h - 3.5}" width="${w + 2}" height="4" rx="1.6" fill="${HOOF}"/>` : "")).join("");

export const ART_PREHISTORICMAMMALS = {
  // ── Woolly Rhino — shaggy humped coat, low broad head, BIG forward nose blade + small brow horn ──
  woollyrhino: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M92 84 Q100 86 99 96" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M97 94 q0 4 2 6 q3 -2 2 -6" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M32 78 C28 58 42 46 58 46 C74 46 84 50 92 60 C100 70 98 82 92 88 C80 94 44 94 34 86 C30 84 32 80 32 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 86 Q62 96 88 86 Q66 92 42 88 Z" fill="${B}" opacity=".85"/>
      <g stroke="${c.line}" stroke-width="1.4" opacity=".4" stroke-linecap="round"><path d="M46 52 v9 M56 49 v10 M66 50 v9 M76 53 v8"/></g>
      <path d="M34 84 q4 8 2 14 M44 88 q2 8 0 14" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".4" stroke-linecap="round"/>
      ${legs(c, 44, 74, 86, 12, 20, true)}
      <path d="M46 104 q0 3 2 3 M76 104 q0 3 2 3" stroke="${c.line}" stroke-width="1.4" opacity=".4"/></g>
    <g class="head-tilt">
      <path d="M40 62 C24 58 12 66 12 78 C12 88 22 90 30 86 C40 82 46 78 47 68 C48 62 44 60 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M38 60 Q40 50 48 52 Q47 61 42 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M14 78 C4 60 16 40 26 42 C24 54 24 66 24 74 Q19 80 14 78 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M26 62 Q26 50 34 46 Q36 55 33 63 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M16 80 q6 3 10 1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="20" cy="80" rx="1.5" ry="1.1" fill="${INK}"/>
      ${eye(34, 68, 3, eyeInk(c))}
    </g>`; },

  // ── Glyptodon — huge smooth armour dome (hex scutes), tiny turtle head, stub legs, ROUND club tail ──
  glyptodon: (c) => { const B = belly(c); const dome = deepen(c.body, .12); return `
    <g class="tail-wag"><path d="M84 88 Q104 86 108 96 Q104 106 92 100 Q88 94 84 92 Z" fill="${dome}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <circle cx="100" cy="96" r="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/><circle cx="100" cy="96" r="2" fill="${deepen(c.body,.3)}"/></g>
    <g class="breathe">
      <path d="M22 96 C18 66 34 42 60 42 C86 42 102 66 98 96 Q60 104 22 96 Z" fill="${dome}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M30 62 q30 -8 60 0 M26 76 q34 -6 68 0 M24 90 q36 -4 72 0" fill="none" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>
      <path d="M44 50 v46 M60 46 v52 M76 50 v46" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>
      ${[[38,60],[52,58],[68,58],[82,62],[45,74],[60,72],[75,74],[40,88],[58,86],[76,88]].map(([x,y])=>`<circle cx="${x}" cy="${y}" r="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.2" opacity=".55"/>`).join("")}
      ${legs(c, 34, 74, 92, 12, 15, true)}</g>
    <g class="head-tilt">
      <path d="M30 78 C14 76 8 84 10 92 C12 100 24 100 30 96 C36 92 38 84 30 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M14 86 Q20 92 28 90" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="14" cy="86" rx="1.6" ry="1.2" fill="${INK}"/>
      ${eye(24, 84, 3, eyeInk(c))}</g>`; },

  // ── Giant Ground Sloth — upright shaggy bulk, small head high, huge curved fore-claws, thick tail ──
  giantgroundsloth: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M74 96 Q92 100 92 112 L74 112 Q70 104 68 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M40 108 C30 84 30 56 44 42 C52 34 66 34 74 44 C86 60 84 88 76 108 Q58 114 40 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 60 C44 76 46 92 52 106 Q62 108 70 104 C74 88 72 70 66 58 Q58 54 48 60 Z" fill="${B}" opacity=".85"/>
      <g stroke="${c.line}" stroke-width="1.4" opacity=".4" stroke-linecap="round"><path d="M42 66 q-2 10 0 20 M74 64 q3 10 1 20 M40 52 q-1 8 1 14"/></g>
      <path d="M46 106 q3 6 8 6 M66 106 q3 6 8 6" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="tail-wag">
      <path d="M46 62 C34 74 26 88 26 98 C26 104 32 106 36 102 C38 94 44 82 54 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <g stroke="${IVORY}" stroke-width="3.4" stroke-linecap="round"><path d="M26 98 q-4 6 -8 8 M28 100 q-2 7 -4 10 M31 101 q0 7 0 11"/></g>
      <g stroke="${c.line}" stroke-width="1" stroke-linecap="round"><path d="M26 98 q-4 6 -8 8 M28 100 q-2 7 -4 10 M31 101 q0 7 0 11"/></g></g>
    <g class="head-tilt">
      <path d="M50 42 C44 30 50 20 60 20 C70 20 76 30 70 42 Q60 48 50 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 32 Q60 44 68 32 Q62 40 52 32 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="30" rx="3.4" ry="2.4" fill="${INK}"/>
      ${eyes(53, 67, 26, 2.6, eyeInk(c))}</g>`; },

  // ── Dire Wolf — robust heavy canid, thick neck ruff, upright ears, blunt strong muzzle, bushy tail ──
  direwolf: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M84 84 C104 84 112 68 104 56 C106 68 96 78 88 80 C86 82 84 82 82 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M102 58 q5 9 -2 16" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".55" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M36 88 C34 66 46 56 62 56 C80 56 90 66 90 84 C90 92 84 96 74 96 L74 108 L66 108 L66 96 L52 96 L52 108 L44 108 L44 90 C38 90 36 90 36 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 90 Q64 98 82 88 Q66 94 50 90 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 46, 66, 90, 8, 18, false)}</g>
    <g class="head-tilt">
      <path d="M34 44 L28 26 L46 38 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M58 40 L66 24 L66 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${pom(52, 58, 14, c.shade, c.line, 13, 2)}
      <path d="M52 42 C44 40 36 44 36 44 C30 46 20 52 16 62 C14 68 20 71 26 67 C29 74 40 74 46 66 C54 64 60 56 56 46 Q54 42 52 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M18 62 C22 70 38 72 46 64 Q36 64 28 62 Q22 62 18 62 Z" fill="${B}" opacity=".7"/>
      <path d="M16 62 l-5 -1 l4 4 l-3 3" fill="${INK}"/>
      <ellipse cx="14" cy="62" rx="1.7" ry="1.3" fill="${INK}"/>
      <path d="M20 66 q7 4 14 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(36, 54, 3, eyeInk(c))}${eye(50, 52, 3, eyeInk(c))}</g>`; },

  // ── Cave Bear — massive low quadruped, high domed forehead, small ears, heavy paws ──────────────
  cavebear: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M88 88 q8 2 6 10" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M32 88 C30 62 46 52 64 52 C84 52 94 64 94 84 C94 94 86 98 74 98 L74 108 L62 108 L62 98 L50 98 L50 108 L40 108 L40 94 C34 94 32 92 32 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 92 Q64 100 84 90 Q66 96 46 92 Z" fill="${B}" opacity=".8"/>
      <path d="M40 94 q-4 8 0 14 M50 98 q-3 6 0 10 M62 98 q3 6 0 10 M74 98 q4 8 0 14" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".45"/>
      ${["",""].map((_,i)=>`<ellipse cx="${i?68:46}" cy="107" rx="7" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M40 40 Q38 30 46 32 Q50 38 48 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      ${mirror(`<path d="M40 40 Q38 30 46 32 Q50 38 48 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>`)}
      <path d="M40 52 C34 34 52 26 60 26 C68 26 86 34 80 52 C86 56 88 66 80 72 C74 60 46 60 40 72 C32 66 34 56 40 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 60 C42 68 44 76 54 78 Q60 80 66 78 C76 76 78 68 74 60 Q60 56 46 60 Z" fill="${B}"/>
      <path d="M52 68 Q60 74 68 68 Q60 72 52 68 Z" fill="${c.shade}"/>
      <path d="M56 64 l4 0 l-2 4 Z" fill="${INK}"/>
      ${eye(50, 54, 3.2, eyeInk(c))}${eye(70, 54, 3.2, eyeInk(c))}</g>`; },

  // ── Andrewsarchus — long low body, LONG toothy skull-snout, hooved toes, wolfish predator ───────
  andrewsarchus: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M90 84 C102 82 106 72 100 66 Q98 72 92 76 Q88 80 86 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M40 86 C38 68 50 60 66 60 C84 60 94 68 94 82 C94 90 88 94 78 94 L78 106 L70 106 L70 94 L54 94 L54 106 L46 106 L46 88 C42 88 40 88 40 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 88 Q66 96 84 86 Q68 92 52 88 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 48, 70, 88, 8, 18, true)}</g>
    <g class="head-tilt">
      <path d="M50 50 L46 38 L58 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 46 C36 48 20 60 8 73 C5 77 9 80 14 79 C28 82 44 78 48 68 C52 62 54 52 52 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M12 74 Q28 79 46 73" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <g fill="#fff" stroke="${c.line}" stroke-width="0.6"><path d="M16 75 l2 5 l2 -5 Z"/><path d="M22 76 l2 5 l2 -5 Z"/><path d="M28 76 l2 5 l2 -5 Z"/></g>
      <path d="M8 73 l-4 -1 l4 4" fill="${INK}"/>
      <ellipse cx="9" cy="72" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(44, 58, 2.8, eyeInk(c))}</g>`; },

  // ── Entelodont — "hell pig": bulky humped body, big head with bony CHEEK KNOBS + tusky jaw ───────
  entelodont: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M90 86 q8 0 8 10" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><path d="M96 94 l2 5 l3 -4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2"/></g>
    <g class="breathe">
      <path d="M42 90 C40 66 52 54 66 54 C82 54 92 64 94 84 C95 92 88 96 78 96 L78 106 L70 106 L70 96 L56 96 L56 106 L48 106 L48 92 C44 92 42 92 42 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M58 58 Q68 52 78 58 Q70 64 60 62 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M54 92 Q68 98 84 90 Q70 96 54 92 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 50, 70, 90, 8, 16, true)}</g>
    <g class="head-tilt">
      <path d="M56 42 L52 30 L64 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 42 C42 40 28 52 20 66 C17 72 24 75 30 71 C40 78 52 74 54 62 C58 54 60 46 56 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M20 66 Q17 72 22 72 Q24 68 22 65 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="21" cy="68" rx="1.6" ry="2" fill="${INK}"/>
      <path d="M42 66 C40 78 50 82 56 76 C59 70 54 62 47 62 Q42 62 42 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M24 70 Q22 78 18 76 Q20 70 23 68 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M24 70 Q32 74 42 70" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(46, 52, 2.8, eyeInk(c))}</g>`; },

  // ── Chalicothere — sloping back (high shoulder / low hip), horse head, long clawed knuckle-walk arms ─
  chalicothere: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M86 82 q10 4 8 16" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="94" cy="98" r="2.6" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M40 66 C42 52 56 46 68 48 C84 50 92 62 92 82 C92 90 86 94 78 94 L78 106 L70 106 L70 94 L60 94 C52 94 46 90 44 82 L44 94 L44 106 L36 106 L36 74 C36 70 38 68 40 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M56 84 Q68 92 82 84 Q70 90 56 86 Z" fill="${B}" opacity=".8"/>
      <path d="M46 60 Q66 54 84 66" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".5" stroke-linecap="round"/>
      <rect x="68" y="90" width="8" height="16" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    <g class="tail-wag">
      <path d="M40 74 C30 82 26 96 30 104 C34 108 40 106 40 100 C40 92 44 84 50 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <g stroke="${IVORY}" stroke-width="3" stroke-linecap="round"><path d="M30 104 q-3 4 -6 6 M33 105 q-1 5 -3 7 M36 105 q0 5 0 7"/></g>
      <g stroke="${c.line}" stroke-width="1" stroke-linecap="round"><path d="M30 104 q-3 4 -6 6 M33 105 q-1 5 -3 7 M36 105 q0 5 0 7"/></g></g>
    <g class="head-tilt">
      <path d="M40 44 L36 32 Q42 34 44 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M48 44 L52 32 Q56 36 52 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M46 48 C40 40 28 40 24 52 C22 60 20 68 24 70 C30 68 30 60 34 56 C38 60 48 58 50 50 Q50 46 46 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M24 66 Q22 70 26 70 Q26 66 24 66 Z" fill="${c.shade}"/>
      <ellipse cx="24" cy="66" rx="1.5" ry="1.8" fill="${INK}"/>
      ${eye(38, 52, 2.8, eyeInk(c))}</g>`; },

  // ── Uintatherium — heavy rhino-body, ornate head with THREE PAIRS of knobs + downward saber tusks ──
  uintatherium: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M92 84 q8 2 6 12" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M96 96 l2 5 l3 -4" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M36 88 C34 64 48 54 66 54 C86 54 96 66 96 84 C96 92 90 96 80 96 L80 108 L72 108 L72 96 L52 96 L52 108 L44 108 L44 90 C40 90 36 90 36 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 92 Q68 100 88 90 Q68 96 48 92 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 48, 70, 90, 10, 18, true)}</g>
    <g class="head-tilt">
      <path d="M56 40 C42 36 28 50 20 66 C17 72 24 75 30 71 C40 78 52 74 54 62 C58 54 60 46 56 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${[[50,44],[40,52],[30,60]].map(([x,y])=>`<path d="M${x-5} ${y+3} Q${x} ${y-8} ${x+5} ${y+3} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M${x-2} ${y-3} Q${x} ${y-6} ${x+2} ${y-3}" fill="none" stroke="${c.shade}" stroke-width="1.6" stroke-linecap="round"/>`).join("")}
      <path d="M28 70 Q26 82 21 80 Q23 71 26 68 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M20 66 Q28 72 40 68" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="21" cy="66" rx="1.5" ry="1.1" fill="${INK}"/>
      ${eye(44, 54, 2.8, eyeInk(c))}</g>`; },

  // ── Basilosaurus — ancient serpentine whale (FLOAT, horizontal, faces right), tiny hind legs, fluke ──
  basilosaurus: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M22 66 Q6 54 6 66 Q2 70 9 72 Q2 76 10 80 Q4 90 22 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M20 70 C34 56 56 54 78 56 C96 58 108 62 112 66 C114 68 112 72 108 72 C96 72 96 80 100 84 C90 88 76 84 66 80 C48 82 30 82 20 76 Q16 74 20 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M32 72 Q60 82 96 74 Q66 82 34 78 Z" fill="${B}" opacity=".85"/>
      <path d="M100 66 Q112 64 112 68 Q106 70 100 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <g fill="#fff" stroke="${c.line}" stroke-width="0.6"><path d="M92 71 l1.5 4 l1.5 -4 Z"/><path d="M98 71 l1.5 4 l1.5 -4 Z"/><path d="M104 70 l1.4 3.5 l1.4 -3.5 Z"/></g>
      <g class="tail-wag"><path d="M52 80 C50 90 44 94 40 92 C42 86 44 82 48 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
      <path d="M74 60 Q78 52 82 58" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(96, 66, 3, eyeInk(c))}</g>`; },

  // ── Doedicurus — armadillo dome (banded) + tail ending in a big SPIKED MACE club ────────────────
  doedicurus: (c) => { const dome = deepen(c.body, .12); return `
    <g class="tail-wag">
      <path d="M80 88 Q92 88 97 92" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M80 88 Q92 88 97 92" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round"/>
      <circle cx="100" cy="94" r="9" fill="${dome}" stroke="${c.line}" stroke-width="2.8"/>
      ${[[-90],[-40],[10],[60],[110]].map(([a])=>{const r=(a*Math.PI/180);return `<path d="M${(100+7*Math.cos(r)).toFixed(1)} ${(94+7*Math.sin(r)).toFixed(1)} l${(7*Math.cos(r)).toFixed(1)} ${(7*Math.sin(r)).toFixed(1)}" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M${(100+7*Math.cos(r)).toFixed(1)} ${(94+7*Math.sin(r)).toFixed(1)} l${(5*Math.cos(r)).toFixed(1)} ${(5*Math.sin(r)).toFixed(1)}" stroke="${IVORY}" stroke-width="1.8" stroke-linecap="round"/>`;}).join("")}</g>
    <g class="breathe">
      <path d="M22 94 C18 66 34 44 58 44 C82 44 98 66 94 94 Q58 102 22 94 Z" fill="${dome}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M26 62 q32 -8 64 0 M24 74 q34 -6 68 0 M23 86 q35 -5 70 0" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".55"/>
      ${[[38,56],[54,54],[70,56],[36,68],[52,66],[68,68],[38,80],[56,80],[72,80]].map(([x,y])=>`<circle cx="${x}" cy="${y}" r="3" fill="${c.body}" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>`).join("")}
      ${legs(c, 34, 72, 90, 11, 15, true)}</g>
    <g class="head-tilt">
      <path d="M30 78 C14 76 8 84 10 92 C12 100 24 100 30 96 C36 92 38 84 30 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M14 86 Q20 92 28 90" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="14" cy="86" rx="1.6" ry="1.2" fill="${INK}"/>
      ${eye(24, 84, 3, eyeInk(c))}</g>`; },

  // ── Irish Elk — stag body, ENORMOUS palmate (broad flat fan) antlers spreading wide ─────────────
  irishelk: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M84 84 q8 0 8 8" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="92" cy="92" r="2.4" fill="${c.shade}"/></g>
    <g class="breathe">
      <ellipse cx="62" cy="82" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M42 86 q20 8 40 0" fill="${B}" opacity=".7"/>
      ${legs(c, 50, 72, 90, 6, 20, true)}</g>
    <path d="M50 80 Q44 58 52 44" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/>
    <path d="M50 80 Q44 58 52 44" fill="none" stroke="${c.body}" stroke-width="8" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M53 50 C38 34 20 34 12 22 C24 24 34 26 44 30 C34 22 24 20 20 10 C32 16 44 22 53 42 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M53 50 C38 34 20 34 12 22 C24 24 34 26 44 30 C34 22 24 20 20 10 C32 16 44 22 53 42 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}</g>
    <g class="head-tilt">
      <path d="M48 44 Q40 42 40 50 Q46 53 51 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M48 44 Q40 42 40 50 Q46 53 51 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M52 46 Q50 64 60 72 Q70 64 68 46 Q60 40 52 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M54 66 q6 5 12 0 Q60 72 54 66 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="68" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 54, 2.6, eyeInk(c))}</g>`; },

  // ── Paraceratherium — giant hornless rhino: long neck, small head high, huge body, pillar legs ───
  paraceratherium: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M92 76 q8 4 6 16" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><circle cx="98" cy="94" r="2.6" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M42 78 C44 60 60 56 74 58 C90 60 96 72 96 84 C96 92 90 96 82 96 L82 108 L74 108 L74 96 L60 96 L60 108 L52 108 L52 92 C46 90 42 84 42 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M56 90 Q70 98 86 88 Q72 94 56 90 Z" fill="${B}" opacity=".8"/>
      <rect x="46" y="90" width="9" height="18" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    <path d="M48 74 Q40 46 50 24" fill="none" stroke="${c.line}" stroke-width="15" stroke-linecap="round"/>
    <path d="M48 74 Q40 46 50 24" fill="none" stroke="${c.body}" stroke-width="11" stroke-linecap="round"/>
    <path d="M44 56 q-2 -12 6 -22" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".45" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M50 24 Q46 16 54 16 Q57 20 55 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M50 22 C42 20 34 24 32 32 C31 38 36 40 42 37 C42 44 52 44 54 36 Q56 26 50 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M32 32 Q38 38 46 35" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="33" cy="32" rx="1.5" ry="1.1" fill="${INK}"/>
      ${eye(45, 30, 2.8, eyeInk(c))}</g>`; },

  // ── Macrauchenia — llama-camel build, long neck, small SOFT TRUNK nose, slender legs ────────────
  macrauchenia: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M86 80 q8 2 7 14" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="93" cy="96" r="2.4" fill="${c.shade}"/></g>
    <g class="breathe">
      <ellipse cx="64" cy="80" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M44 84 q20 8 40 0" fill="${B}" opacity=".7"/>
      ${legs(c, 52, 74, 88, 7, 22, true)}</g>
    <path d="M52 78 Q40 50 48 26" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
    <path d="M52 78 Q40 50 48 26" fill="none" stroke="${c.body}" stroke-width="9" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M45 26 Q42 12 50 16 Q52 24 50 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M51 26 Q49 12 57 16 Q58 24 55 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M48 26 C40 24 30 28 26 38 C24 46 22 52 28 52 C30 46 32 42 36 40 C40 44 50 42 52 34 Q54 28 48 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M28 46 Q26 54 22 54 Q22 46 26 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M24 52 q4 3 8 1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="24" cy="50" rx="1.5" ry="1.2" fill="${INK}"/>
      ${eye(42, 34, 2.6, eyeInk(c))}</g>`; },

  // ── Thylacine — dog-like marsupial with dark tiger STRIPES over the rear back + stiff tapering tail ─
  thylacine: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M86 84 C102 84 108 96 104 106" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M86 84 C102 84 108 96 104 106" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M38 86 C36 68 48 60 64 60 C82 60 90 68 90 82 C90 90 84 94 76 94 L76 106 L68 106 L68 94 L52 94 L52 106 L44 106 L44 90 C40 90 38 88 38 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 90 Q64 96 82 88 Q66 92 50 90 Z" fill="${B}" opacity=".8"/>
      <g stroke="${c.shade}" stroke-width="3.4" stroke-linecap="round"><path d="M62 64 q-1 8 0 16 M70 65 q1 8 0 15 M78 68 q1 6 0 12 M86 72 q1 5 0 9"/></g>
      ${legs(c, 46, 66, 90, 7, 18, false)}</g>
    <g class="head-tilt">
      <path d="M42 44 L38 32 Q44 34 46 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M52 42 L54 30 Q60 34 56 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M48 46 C40 44 26 48 20 60 C18 66 26 68 32 64 C36 70 46 68 50 60 Q52 50 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M20 60 Q28 64 36 61" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M20 60 l-4 -1 l4 3" fill="${INK}"/>
      ${eye(40, 52, 2.8, eyeInk(c))}</g>`; },

  // ── Diprotodon — giant wombat: heavy round body, short stout legs, blunt bear-ish face, small ears ─
  diprotodon: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M90 90 q6 0 6 8" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M34 92 C32 66 48 56 66 56 C86 56 96 68 96 88 C96 96 88 100 76 100 L76 108 L64 108 L64 100 L52 100 L52 108 L42 108 L42 96 C36 96 34 94 34 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 94 Q66 102 86 92 Q66 98 46 94 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 46, 68, 94, 11, 14, true)}</g>
    <g class="head-tilt">
      <ellipse cx="44" cy="43" rx="5.2" ry="5.6" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      ${mirror(`<ellipse cx="44" cy="43" rx="5.2" ry="5.6" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>`)}
      <path d="M42 56 C36 40 52 32 60 32 C68 32 84 40 78 56 C84 60 84 70 76 74 C70 64 50 64 44 74 C36 70 36 60 42 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 62 C44 70 48 78 60 78 C72 78 76 70 72 62 Q60 58 48 62 Z" fill="${B}"/>
      <path d="M54 70 Q60 74 66 70 Q60 73 54 70 Z" fill="${c.shade}"/>
      <path d="M58 66 l4 0 l-2 3 Z" fill="${INK}"/>
      ${eye(52, 54, 3, eyeInk(c))}${eye(68, 54, 3, eyeInk(c))}</g>`; },

  // ── Short-faced Bear — bear on TALL long legs, short blunt face, upright imposing stance ─────────
  shortfacedbear: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M84 72 q7 2 5 10" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M42 72 C40 52 52 44 62 44 C80 44 88 54 88 70 C88 80 82 84 76 84 L78 110 L68 110 L68 84 L52 84 L50 110 L40 110 L42 82 C38 80 42 76 42 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 76 Q62 84 82 74 Q66 80 50 76 Z" fill="${B}" opacity=".8"/>
      <ellipse cx="45" cy="108" rx="6.5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="73" cy="108" rx="6.5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="head-tilt">
      <path d="M40 34 Q38 24 46 26 Q49 32 47 38 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M40 34 Q38 24 46 26 Q49 32 47 38 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M38 42 C34 26 52 20 60 20 C68 20 86 26 82 42 C88 46 88 54 80 58 C76 50 44 50 40 58 C32 54 32 46 38 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 48 C44 53 50 58 60 58 C70 58 76 53 72 48 Q60 45 48 48 Z" fill="${B}"/>
      <path d="M53 52 Q60 56 67 52 Q60 55 53 52 Z" fill="${c.shade}"/>
      <path d="M57 49 l6 0 l-3 4 Z" fill="${INK}"/>
      ${eye(48, 42, 3, eyeInk(c))}${eye(72, 42, 3, eyeInk(c))}</g>`; },

  // ── Aurochs — wild ox: muscular, shoulder hump, big forward-curving pale horns, side profile ─────
  aurochs: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M90 84 Q98 88 96 106" fill="none" stroke="${c.line}" stroke-width="3.6" stroke-linecap="round"/><path d="M94 104 q0 4 2 6 q3 -2 2 -6" fill="${INK}"/></g>
    <g class="breathe">
      <path d="M36 88 C34 68 46 58 56 56 C60 46 70 46 72 58 C86 60 94 70 94 84 C94 92 88 96 78 96 L78 108 L70 108 L70 96 L52 96 L52 108 L44 108 L44 90 C38 90 36 90 36 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 92 Q66 100 86 90 Q68 96 50 92 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 48, 70, 90, 8, 18, true)}</g>
    <g class="head-tilt">
      <path d="M46 46 C36 44 26 50 24 62 C22 70 30 72 36 68 C40 74 50 72 52 62 Q54 50 46 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M40 46 C30 36 14 40 12 30 Q26 30 40 40 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 46 C42 34 46 22 56 22 Q52 34 52 46 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M28 66 Q34 70 42 66" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M24 64 l-4 0 l4 3" fill="${INK}"/>
      <ellipse cx="26" cy="62" rx="1.5" ry="1.1" fill="${INK}"/>
      ${eye(42, 56, 2.8, eyeInk(c))}</g>`; },

  // ── Gigantopithecus — giant ape sitting, sagittal-crest head, flat face, long resting arms ──────
  gigantopithecus: (c) => { const B = belly(c); return `
    <g class="breathe">
      <path d="M32 104 C28 76 40 60 60 60 C80 60 92 76 88 104 Q60 110 32 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 96 C44 82 48 72 60 72 C72 72 76 82 74 96 Q60 102 46 96 Z" fill="${B}" opacity=".85"/>
      <ellipse cx="48" cy="105" rx="8" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="72" cy="105" rx="8" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="tail-wag">
      <path d="M36 66 C22 72 16 92 22 104 C28 106 34 102 32 94 C30 84 36 76 44 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M36 66 C22 72 16 92 22 104 C28 106 34 102 32 94 C30 84 36 76 44 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}</g>
    <g class="head-tilt">
      <path d="M56 26 Q60 18 64 26" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 46 C42 28 60 26 60 26 C60 26 78 28 78 46 C78 62 68 66 60 66 C52 66 42 62 42 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${mirror(`<ellipse cx="43" cy="44" rx="3.6" ry="5.4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`)}
      <ellipse cx="43" cy="44" rx="3.6" ry="5.4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M48 46 C48 36 60 34 60 34 C60 34 72 36 72 48 C72 60 66 62 60 62 C54 62 48 58 48 46 Z" fill="${B}"/>
      <path d="M52 44 q4 -3 8 0 M60 44 q4 -3 8 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M56 50 q4 3 8 0 M58 49 v3 M62 49 v3" stroke="${c.line}" stroke-width="1.4" fill="none"/>
      <path d="M52 55 Q60 60 68 55" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(53, 67, 44, 2.7, eyeInk(c))}</g>`; },

  // ── Arsinoitherium — rhino-like bulk with TWIN ENORMOUS nose horns rising together (front pair) ──
  arsinoitherium: (c) => { const B = belly(c); return `
    <g class="tail-wag"><path d="M90 86 q8 2 6 12" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M94 98 l2 5 l3 -4" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M36 88 C34 64 48 54 66 54 C86 54 96 66 96 84 C96 92 90 96 80 96 L80 108 L72 108 L72 96 L52 96 L52 108 L44 108 L44 90 C40 90 36 90 36 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 92 Q68 100 88 90 Q68 96 48 92 Z" fill="${B}" opacity=".8"/>
      ${legs(c, 48, 70, 90, 10, 18, true)}</g>
    <g class="head-tilt">
      <path d="M26 62 C22 50 30 40 42 40 C52 40 58 44 58 52 Q58 62 48 66 C40 70 30 70 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M28 46 C20 30 26 14 34 14 C36 26 34 38 36 48 Q32 50 28 46 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M44 44 C40 28 46 12 54 12 C56 24 52 38 52 48 Q48 48 44 44 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 46 q3 -14 8 -20" fill="none" stroke="${HORNSH}" stroke-width="1.8" opacity=".7" stroke-linecap="round"/>
      <path d="M24 62 Q30 66 38 63" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M24 62 l-4 -1 l4 3" fill="${INK}"/>
      <ellipse cx="26" cy="60" rx="1.5" ry="1.1" fill="${INK}"/>
      ${eye(48, 56, 2.8, eyeInk(c))}</g>`; },
};

// roster metadata — every `n` slugifies (lowercase, [a-z0-9] only) to an ART_PREHISTORICMAMMALS key above
export const ROSTER_PREHISTORICMAMMALS = [
  { n: "Woolly Rhino",       e: "🦏", tier: 4, float: false },
  { n: "Glyptodon",          e: "🐢", tier: 3, float: false },
  { n: "Giant Ground Sloth", e: "🦥", tier: 3, float: false },
  { n: "Dire Wolf",          e: "🐺", tier: 3, float: false },
  { n: "Cave Bear",          e: "🐻", tier: 4, float: false },
  { n: "Andrewsarchus",      e: "🐺", tier: 4, float: false },
  { n: "Entelodont",         e: "🐗", tier: 3, float: false },
  { n: "Chalicothere",       e: "🦍", tier: 3, float: false },
  { n: "Uintatherium",       e: "🦏", tier: 3, float: false },
  { n: "Basilosaurus",       e: "🐋", tier: 4, float: true  },
  { n: "Doedicurus",         e: "🐢", tier: 3, float: false },
  { n: "Irish Elk",          e: "🦌", tier: 4, float: false },
  { n: "Paraceratherium",    e: "🦏", tier: 5, float: false },
  { n: "Macrauchenia",       e: "🦙", tier: 3, float: false },
  { n: "Thylacine",          e: "🐅", tier: 3, float: false },
  { n: "Diprotodon",         e: "🐻", tier: 3, float: false },
  { n: "Short-faced Bear",   e: "🐻", tier: 4, float: false },
  { n: "Aurochs",            e: "🐂", tier: 3, float: false },
  { n: "Gigantopithecus",    e: "🦍", tier: 4, float: false },
  { n: "Arsinoitherium",     e: "🦏", tier: 3, float: false },
];
