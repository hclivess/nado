// primates.js — BESPOKE hand-drawn SVG art for PRIMATES (NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,62), within x,y ∈ [8,112].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/cape/face-ring), c.line (outline stroke).
// Fixed identity colours allowed for signature features (mandrill face, gelada chest, ring-tail bands).
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const BLUE = "#3f6fb0"; // mandrill facial ridges / bare skin
const RED  = "#d1443c"; // mandrill nose stripe / gelada bleeding-heart chest
const GOLD = "#f2c94c"; // mandrill beard / gelada mane accent
const AMBER = "#d8a23c"; // huge nocturnal iris (tarsier/loris/galago/bushbaby)
const WHT  = "#fbf6ee"; // ring-tail white bands / colobus cape highlight / nose stripe
const PINK = "#e79a9a"; // bare pink face (macaque) / bonobo lips
const BRANCH = "#8a6a4a"; // wood the clingers grip

// one enormous glossy nocturnal eye: coloured iris, big black pupil, white catchlight
const bigEye = (x, y, r, iris, line) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${iris}" stroke="${line}" stroke-width="2.2"/>` +
  `<circle cx="${x}" cy="${y}" r="${(r * 0.5).toFixed(1)}" fill="${INK}"/>` +
  `<circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.32).toFixed(1)}" r="${(r * 0.24).toFixed(1)}" fill="#fff" opacity=".95"/>`;

export const ART_PRIMATES = {
  // ── Orangutan — wide cheek-flange face disc, small top-knot, long shaggy hanging arms, potbelly ──
  orangutan: (c) => `
    <g class="tail-wag">
      ${mirror(`<path d="M42 58 Q14 62 16 98 Q26 100 30 84 Q36 74 48 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M16 96 l-3 6 M22 98 l-2 6 M28 96 l0 6" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`)}
      <path d="M42 58 Q14 62 16 98 Q26 100 30 84 Q36 74 48 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M16 96 l-3 6 M22 98 l-2 6 M28 96 l0 6" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M42 66 Q40 102 60 102 Q80 102 78 66 Q78 54 60 54 Q42 54 42 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="84" rx="12" ry="13" fill="${c.shade}" opacity=".5"/>
      <path d="M46 68 q-4 8 -2 16 M74 68 q4 8 2 16" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M55 26 Q60 18 65 26" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M34 46 Q28 30 46 27 Q60 23 74 27 Q92 30 86 46 Q92 60 72 64 Q60 68 48 64 Q28 60 34 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M47 42 Q47 30 60 30 Q73 30 73 42 Q73 56 60 60 Q47 56 47 42 Z" fill="${c.shade}"/>
      <path d="M50 40 q10 -3 20 0" stroke="${INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      <path d="M56 47 Q60 51 64 47 M58 47 v3 M62 47 v3" stroke="${INK}" stroke-width="1.5" fill="none"/>
      <path d="M53 53 Q60 58 67 53" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(54, 66, 41, 2.5, eyeInk(c))}
    </g>`,

  // ── Gibbon — hugely long arms flung overhead to a handhold, slender body, pale face ring ─────────
  gibbon: (c) => `
    <g class="tail-wag">
      ${mirror(`<path d="M48 60 Q24 46 22 22" fill="none" stroke="${c.line}" stroke-width="9" stroke-linecap="round"/><path d="M48 60 Q24 46 22 22" fill="none" stroke="${c.body}" stroke-width="6" stroke-linecap="round"/><circle cx="22" cy="20" r="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M48 60 Q24 46 22 22" fill="none" stroke="${c.line}" stroke-width="9" stroke-linecap="round"/><path d="M48 60 Q24 46 22 22" fill="none" stroke="${c.body}" stroke-width="6" stroke-linecap="round"/><circle cx="22" cy="20" r="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="74" rx="14" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="78" rx="8" ry="10" fill="${c.shade}" opacity=".5"/>
      ${mirror(`<path d="M52 88 Q46 100 54 102 Q58 96 58 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <path d="M52 88 Q46 100 54 102 Q58 96 58 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="46" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="49" rx="10" ry="11" fill="${c.shade}"/>
      <path d="M53 44 q3 -3 6 0 M61 44 q3 -3 6 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M58 50 q2 2 4 0 M59 49 v3 M61 49 v3" stroke="${INK}" stroke-width="1.3" fill="none"/>
      <path d="M54 55 Q60 59 66 55" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(54, 66, 46, 2.5, eyeInk(c))}
    </g>`,

  // ── Baboon — heavy mane, long dog-like protruding muzzle, close-set eyes, upcurled tail ──────────
  baboon: (c) => `
    <g class="tail-wag">
      <path d="M78 84 Q100 84 96 62" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M78 84 Q100 84 96 62" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M40 92 Q34 60 60 58 Q86 60 80 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 88 q10 6 20 0" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".6"/>
    </g>
    <g class="head-tilt">
      ${pom(58, 44, 20, c.body, c.line, 12, 2.4)}
      <path d="M60 46 Q58 38 68 38 Q82 40 84 50 Q82 60 68 60 Q58 58 60 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="83" cy="50" rx="3.5" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="83" cy="47" rx="1.2" ry="0.9" fill="${INK}"/><ellipse cx="83" cy="53" rx="1.2" ry="0.9" fill="${INK}"/>
      <path d="M66 44 q8 -2 14 2" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M68 57 q7 2 12 -1" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(52, 62, 38, 2.4, eyeInk(c))}
    </g>`,

  // ── Mandrill — the signature colourful face: blue ridged cheeks, red nose stripe, gold beard ─────
  mandrill: (c) => `
    <g class="breathe">
      <path d="M42 94 Q36 66 60 62 Q84 66 78 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${mirror(`<path d="M44 74 Q26 78 30 96 Q38 94 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M44 74 Q26 78 30 96 Q38 94 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${pom(60, 46, 22, GOLD, c.line, 14, 2.4)}
      <path d="M46 44 Q46 26 60 26 Q74 26 74 44 Q74 62 60 64 Q46 62 46 44 Z" fill="${INK}"/>
      <path d="M46 42 Q40 34 44 48 Q46 58 52 58 Q54 46 52 40 Q49 36 46 42 Z" fill="${BLUE}" stroke="${c.line}" stroke-width="1.6"/>
      ${mirror(`<path d="M46 42 Q40 34 44 48 Q46 58 52 58 Q54 46 52 40 Q49 36 46 42 Z" fill="${BLUE}" stroke="${c.line}" stroke-width="1.6"/>`)}
      <path d="M48 40 q1 8 1 14 M52 42 q0 6 0 12" stroke="${INK}" stroke-width="1.2" opacity=".5" fill="none"/>
      ${mirror(`<path d="M48 40 q1 8 1 14 M52 42 q0 6 0 12" stroke="${INK}" stroke-width="1.2" opacity=".5" fill="none"/>`)}
      <path d="M58 34 Q60 30 62 34 L63 56 Q60 60 57 56 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M58 54 q2 3 4 0 M59 54 v-2 M61 54 v-2" stroke="${INK}" stroke-width="1.3" fill="none"/>
      <path d="M50 36 q4 -3 8 0 M62 36 q4 -3 8 0" stroke="#fff" stroke-width="1.4" fill="none" opacity=".6" stroke-linecap="round"/>
      ${eyes(53, 67, 40, 2.4, "#e9edf2")}
    </g>`,

  // ── Macaque — fluffy fur crown, bare pink face, snow-monkey rounded body ─────────────────────────
  macaque: (c) => `
    <g class="breathe">${pom(60, 82, 19, c.body, c.line, 15, 2.4)}
      <ellipse cx="60" cy="86" rx="11" ry="8" fill="${c.shade}" opacity=".5"/></g>
    <g class="tail-wag">
      ${mirror(`<g><path d="M47 70 Q37 78 40 90 Q42 100 53 97 Q60 95 58 87 Q55 78 56 71 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M44 94 q1 4 3 5 M48 95 q1 4 3 5 M52 94 q0 4 2 5" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round"/></g>`)}
      <g><path d="M47 70 Q37 78 40 90 Q42 100 53 97 Q60 95 58 87 Q55 78 56 71 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M44 94 q1 4 3 5 M48 95 q1 4 3 5 M52 94 q0 4 2 5" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round"/></g>
    </g>
    <g class="head-tilt">
      ${pom(60, 46, 20, c.body, c.line, 11, 2.4)}
      <path d="M48 48 Q48 34 60 34 Q72 34 72 48 Q72 60 60 62 Q48 60 48 48 Z" fill="${PINK}" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M50 42 q4 -3 8 0 M62 42 q4 -3 8 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M57 50 q3 3 6 0 M59 50 v3 M61 50 v3" stroke="${INK}" stroke-width="1.3" fill="none"/>
      <path d="M53 56 Q60 60 67 56" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eyes(54, 66, 44, 2.5, INK)}
    </g>`,

  // ── Ring-Tailed Lemur — banded ringed tail curling up, white face, black eye patches, amber eyes ─
  ringtailedlemur: (c) => `
    <g class="tail-wag">
      <path d="M74 84 Q102 78 96 44 Q92 22 68 20" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
      <path d="M74 84 Q102 78 96 44 Q92 22 68 20" fill="none" stroke="${WHT}" stroke-width="10" stroke-linecap="round"/>
      <path d="M74 84 Q102 78 96 44 Q92 22 68 20" fill="none" stroke="${INK}" stroke-width="10" stroke-linecap="round" stroke-dasharray="7 9"/>
    </g>
    <path d="M47 48 L65 48 L64 68 L46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="breathe"><ellipse cx="54" cy="80" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="54" cy="84" rx="10" ry="8" fill="${c.shade}" opacity=".55"/></g>
    <g class="head-tilt">
      <path d="M46 30 L42 18 L54 28 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 30 L70 18 L58 28 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="56" cy="40" rx="15" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="56" cy="40" rx="11" ry="11" fill="${WHT}"/>
      <path d="M52 40 Q46 32 50 30 Q56 32 56 40 Q55 46 52 40 Z" fill="${INK}"/>
      <path d="M60 40 Q66 32 62 30 Q56 32 56 40 Q57 46 60 40 Z" fill="${INK}"/>
      <path d="M50 46 Q56 56 62 46 Q60 52 56 52 Q52 52 50 46 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M53 48 L56 52 L59 48 Z" fill="${INK}"/>
      <circle cx="51" cy="39" r="3" fill="${AMBER}"/><circle cx="51" cy="39" r="1.5" fill="${INK}"/><circle cx="52" cy="38" r="0.8" fill="#fff"/>
      <circle cx="61" cy="39" r="3" fill="${AMBER}"/><circle cx="61" cy="39" r="1.5" fill="${INK}"/><circle cx="62" cy="38" r="0.8" fill="#fff"/>
    </g>`,

  // ── Tarsier — enormous saucer eyes filling the face, tiny body, long gripping fingers, thin tail ─
  tarsier: (c) => `
    <g class="tail-wag">
      <path d="M56 92 Q52 112 62 110" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M56 92 Q52 112 62 110" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>
    </g>
    <g class="breathe"><ellipse cx="60" cy="78" rx="14" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="82" rx="7" ry="8" fill="${c.shade}" opacity=".5"/>
      ${mirror(`<path d="M50 74 q-8 6 -6 16 M50 74 q-6 8 -3 17 M50 74 q-3 9 0 18" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>`)}
      <path d="M50 74 q-8 6 -6 16 M50 74 q-6 8 -3 17 M50 74 q-3 9 0 18" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      ${mirror(`<path d="M48 34 Q40 24 44 40 Q48 44 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M48 34 Q40 24 44 40 Q48 44 52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="60" cy="44" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${bigEye(51, 42, 8.5, AMBER, c.line)}
      ${bigEye(69, 42, 8.5, AMBER, c.line)}
      <path d="M58 54 L60 57 L62 54 Z" fill="${INK}"/>
      <path d="M55 59 q5 3 10 0" stroke="${INK}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
    </g>`,

  // ── Marmoset — big fan-shaped white ear tufts, white forehead blaze, banded tail, tiny ──────────
  marmoset: (c) => `
    <g class="tail-wag">
      <path d="M72 84 Q98 82 94 52" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
      <path d="M72 84 Q98 82 94 52" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
      <path d="M72 84 Q98 82 94 52" fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round" stroke-dasharray="4 7" opacity=".8"/>
    </g>
    <path d="M48 56 L64 56 L64 69 L48 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="breathe"><ellipse cx="56" cy="80" rx="15" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    <g class="head-tilt">
      <circle cx="56" cy="46" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 46 Q26 34 30 50 Q26 60 34 58 Q30 50 44 50 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M68 46 Q86 34 82 50 Q86 60 78 58 Q82 50 68 50 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="56" cy="40" rx="4" ry="5" fill="${WHT}"/>
      <ellipse cx="56" cy="50" rx="9" ry="8" fill="${c.shade}" opacity=".5"/>
      <path d="M53 55 L56 58 L59 55 Z" fill="${INK}"/>
      <path d="M50 59 q6 3 12 0" stroke="${INK}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
      ${eyes(51, 61, 46, 2.4, eyeInk(c))}
    </g>`,

  // ── Capuchin — dark fur cap over pale heart-shaped face, curled prehensile tail ─────────────────
  capuchin: (c) => `
    <g class="tail-wag">
      <path d="M72 82 Q100 84 96 54 Q94 42 82 46" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M72 82 Q100 84 96 54 Q94 42 82 46" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
    </g>
    <path d="M48 55 L64 55 L63 68 L46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="breathe"><ellipse cx="54" cy="80" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 74 Q54 68 64 74" fill="${c.shade}" opacity=".4"/></g>
    <g class="head-tilt">
      <circle cx="56" cy="44" r="15" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 44 Q42 26 56 26 Q70 26 70 44 Q64 36 56 36 Q48 36 42 44 Z" fill="${INK}"/>
      <path d="M47 45 Q47 39 56 39 Q65 39 65 45 Q65 55 56 60 Q47 55 47 45 Z" fill="${c.shade}"/>
      <path d="M50 44 q3 -2 6 0 M59 44 q3 -2 6 0" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <path d="M53 49 q3 2 6 0 M55 49 v3 M57 49 v3" stroke="${INK}" stroke-width="1.3" fill="none"/>
      <path d="M50 55 Q56 59 62 55" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eyes(51, 61, 45, 2.4, INK)}
    </g>`,

  // ── Howler Monkey — hunched with a big beard/throat sac, mouth open mid-howl, curled tail ────────
  howlermonkey: (c) => `
    <g class="tail-wag">
      <path d="M46 78 Q22 82 26 52 Q28 40 40 44" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
      <path d="M46 78 Q22 82 26 52 Q28 40 40 44" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
    </g>
    <g class="breathe"><path d="M46 92 Q42 66 60 62 Q80 66 76 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${pom(60, 44, 20, c.body, c.line, 13, 2.4)}
      <path d="M48 52 Q48 74 60 76 Q72 74 72 52 Q60 58 48 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 42 Q50 32 60 32 Q70 32 70 42 Q70 50 60 52 Q50 50 50 42 Z" fill="${c.shade}"/>
      <path d="M52 38 q3 -2 6 0 M62 38 q3 -2 6 0" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <ellipse cx="60" cy="48" rx="2" ry="1.4" fill="${INK}"/>
      <ellipse cx="60" cy="59" rx="6" ry="8" fill="${INK}"/>
      <ellipse cx="60" cy="55" rx="4" ry="2.4" fill="#fff" opacity=".85"/>
      ${eyes(55, 65, 40, 2.3, eyeInk(c))}
    </g>`,

  // ── Spider Monkey — gangly long limbs splayed, long curling prehensile tail, small head ─────────
  spidermonkey: (c) => `
    <g class="tail-wag">
      <path d="M50 76 Q18 78 20 44 Q22 26 40 30 Q30 34 32 48 Q34 66 50 66" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M50 76 Q18 78 20 44 Q22 26 40 30 Q30 34 32 48 Q34 66 50 66" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
    </g>
    ${mirror(`<path d="M52 66 Q32 74 28 96" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M52 66 Q32 74 28 96" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>`)}
    <path d="M52 66 Q32 74 28 96" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M52 66 Q32 74 28 96" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>
    ${mirror(`<path d="M53 62 Q38 56 33 46" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M53 62 Q38 56 33 46" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>`)}
    <path d="M53 62 Q38 56 33 46" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M53 62 Q38 56 33 46" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>
    <g class="breathe"><ellipse cx="60" cy="70" rx="13" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="74" rx="7" ry="9" fill="${c.shade}" opacity=".5"/></g>
    <g class="head-tilt">
      <circle cx="62" cy="44" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 44 Q55 36 62 36 Q69 36 69 44 Q69 52 62 54 Q55 52 55 44 Z" fill="${c.shade}"/>
      <path d="M57 41 q2 -2 4 0 M63 41 q2 -2 4 0" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      <path d="M60 46 q2 2 4 0 M61 46 v3 M63 46 v3" stroke="${INK}" stroke-width="1.2" fill="none"/>
      <path d="M57 51 Q62 54 67 51" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(58, 66, 43, 2.3, eyeInk(c))}
    </g>`,

  // ── Proboscis Monkey — big pendulous drooping nose over the mouth, round potbelly ───────────────
  proboscismonkey: (c) => `
    <g class="tail-wag">
      ${mirror(`<path d="M46 78 Q26 82 30 98 Q38 96 46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M46 78 Q26 82 30 98 Q38 96 46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 92 Q34 60 60 56 Q86 60 80 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="15" ry="14" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="42" rx="16" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 40 Q48 30 60 30 Q72 30 72 40 Q72 48 66 50 L54 50 Q48 48 48 40 Z" fill="${c.shade}"/>
      <path d="M50 37 q4 -3 8 0 M62 37 q4 -3 8 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(54, 66, 38, 2.4, eyeInk(c))}
      <path d="M56 44 Q54 62 60 66 Q66 62 64 44 Q60 42 56 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 50 q2 8 0 12 M62 50 q-2 8 0 12" stroke="${c.line}" stroke-width="1" opacity=".4" fill="none"/>
      <path d="M56 67 q4 3 8 0" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </g>`,

  // ── Slow Loris — huge round eyes with dark eye-rings, round body, slow clinging hands, no tail ───
  slowloris: (c) => `
    <g class="breathe"><ellipse cx="60" cy="76" rx="18" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="80" rx="9" ry="9" fill="${c.shade}" opacity=".5"/>
      ${mirror(`<path d="M46 72 q-8 4 -8 14 q6 2 10 -3 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M46 72 q-8 4 -8 14 q6 2 10 -3 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${mirror(`<circle cx="47" cy="38" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <circle cx="47" cy="38" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="60" cy="46" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="51" cy="44" rx="8" ry="10" fill="${INK}" opacity=".85"/>
      <ellipse cx="69" cy="44" rx="8" ry="10" fill="${INK}" opacity=".85"/>
      <path d="M60 32 L57 56 L63 56 Z" fill="${c.shade}"/>
      ${bigEye(51, 45, 7, AMBER, c.line)}
      ${bigEye(69, 45, 7, AMBER, c.line)}
      <path d="M58 54 L60 57 L62 54 Z" fill="${INK}"/>
      <path d="M56 59 q4 2 8 0" stroke="${INK}" stroke-width="1.2" fill="none" stroke-linecap="round"/>
    </g>`,

  // ── Galago — big eyes, huge rounded ears, long springy hind legs mid-leap, long tail ────────────
  galago: (c) => `
    <g class="tail-wag">
      <path d="M52 82 Q28 90 22 66" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M52 82 Q28 90 22 66" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
    </g>
    ${mirror(`<path d="M54 78 Q66 92 58 104" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M54 78 Q66 92 58 104" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>`)}
    <path d="M54 78 Q66 92 58 104" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M54 78 Q66 92 58 104" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>
    <g class="breathe"><ellipse cx="56" cy="70" rx="14" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/></g>
    <g class="head-tilt">
      ${mirror(`<path d="M48 40 Q34 22 32 42 Q34 52 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M44 42 Q38 34 38 42 Z" fill="${c.shade}"/>`)}
      <path d="M48 40 Q34 22 32 42 Q34 52 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M44 42 Q38 34 38 42 Z" fill="${c.shade}"/>
      <circle cx="56" cy="46" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 40 v14" stroke="${WHT}" stroke-width="2" opacity=".6"/>
      ${bigEye(50, 46, 6.5, AMBER, c.line)}
      ${bigEye(62, 46, 6.5, AMBER, c.line)}
      <path d="M54 53 L56 56 L58 53 Z" fill="${INK}"/>
    </g>`,

  // ── Gelada — red hourglass "bleeding-heart" chest patch, big flowing mane, heavy brow ───────────
  gelada: (c) => `
    <g class="breathe">
      <path d="M40 94 Q34 62 60 58 Q86 62 80 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 66 Q60 60 68 66 Q64 74 68 82 Q60 90 52 82 Q56 74 52 66 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${mirror(`<path d="M44 74 Q28 78 32 94 Q40 92 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M44 74 Q28 78 32 94 Q40 92 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${pom(60, 44, 23, c.body, c.line, 15, 2.4)}
      <path d="M50 26 q10 -4 20 0" stroke="${GOLD}" stroke-width="2.4" fill="none" opacity=".7" stroke-linecap="round"/>
      <path d="M48 44 Q48 28 60 28 Q72 28 72 44 Q72 58 60 60 Q48 58 48 44 Z" fill="${c.shade}"/>
      <path d="M49 40 q11 -4 22 0" stroke="${INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      <path d="M56 48 q4 3 8 0 M58 48 v3 M62 48 v3" stroke="${INK}" stroke-width="1.5" fill="none"/>
      <path d="M53 54 Q60 60 67 54" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(54, 66, 42, 2.4, eyeInk(c))}
    </g>`,

  // ── Colobus — long flowing white cape/mantle along the flanks + white-tufted tail, black face ────
  colobus: (c) => `
    <g class="tail-wag">
      <path d="M76 82 Q104 76 98 42" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M76 82 Q104 76 98 42" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
      ${pom(98, 34, 10, c.shade, c.line, 9, 2)}
    </g>
    <g class="breathe">
      <path d="M44 92 Q40 64 60 60 Q80 64 76 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 60 Q22 74 34 96 Q40 84 44 74 Q42 66 40 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M40 60 Q22 74 34 96 Q40 84 44 74 Q42 66 40 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <path d="M40 66 q-6 12 -3 24 M80 66 q6 12 3 24" stroke="${WHT}" stroke-width="1.4" fill="none" opacity=".55"/>
    </g>
    <g class="head-tilt">
      ${pom(60, 44, 18, c.shade, c.line, 12, 2.4)}
      <ellipse cx="60" cy="46" rx="12" ry="13" fill="${INK}"/>
      <path d="M52 42 q3 -2 6 0 M62 42 q3 -2 6 0" stroke="${c.shade}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M57 49 L60 52 L63 49 Z" fill="${c.shade}"/>
      <path d="M54 54 Q60 58 66 54" stroke="${c.shade}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(55, 65, 43, 2.4, "#e9edf2")}
    </g>`,

  // ── Langur — black face framed by a pale ruff, top crest tuft, very long tail arcing overhead ────
  langur: (c) => `
    <g class="tail-wag">
      <path d="M74 84 Q106 84 102 40 Q100 22 84 24" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M74 84 Q106 84 102 40 Q100 22 84 24" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>
    </g>
    <g class="breathe"><path d="M42 92 Q38 66 58 62 Q80 66 76 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="58" cy="82" rx="12" ry="12" fill="${c.shade}" opacity=".5"/></g>
    <g class="head-tilt">
      ${pom(56, 44, 18, c.shade, c.line, 13, 2.2)}
      <path d="M50 30 Q56 20 62 30" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="56" cy="46" rx="11" ry="12" fill="${INK}"/>
      <path d="M49 43 q3 -2 6 0 M57 43 q3 -2 6 0" stroke="${c.shade}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <path d="M53 50 L56 53 L59 50 Z" fill="${c.shade}"/>
      <path d="M51 55 Q56 58 61 55" stroke="${c.shade}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eyes(51, 61, 44, 2.4, "#e9edf2")}
    </g>`,

  // ── Bonobo — slender black face with pink lips, centre-parted hair, gracile build ───────────────
  bonobo: (c) => `
    <g class="breathe"><ellipse cx="60" cy="82" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="86" rx="10" ry="8" fill="${c.shade}" opacity=".5"/></g>
    <g class="tail-wag">
      ${mirror(`<g><path d="M47 70 Q37 78 40 90 Q42 100 53 97 Q60 95 58 87 Q55 78 56 71 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M44 94 q1 4 3 5 M48 95 q1 4 3 5 M52 94 q0 4 2 5" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round"/></g>`)}
      <g><path d="M47 70 Q37 78 40 90 Q42 100 53 97 Q60 95 58 87 Q55 78 56 71 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M44 94 q1 4 3 5 M48 95 q1 4 3 5 M52 94 q0 4 2 5" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round"/></g>
    </g>
    <g class="head-tilt">
      ${mirror(`<circle cx="44" cy="44" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="44" cy="44" r="3" fill="${c.shade}"/>`)}
      <circle cx="44" cy="44" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="44" cy="44" r="3" fill="${c.shade}"/>
      <circle cx="60" cy="46" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M43 44 Q46 28 60 26 Q74 28 77 44 Q70 34 60 34 Q50 34 43 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 26 L60 36" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M49 48 Q49 38 60 38 Q71 38 71 48 Q71 60 60 62 Q49 60 49 48 Z" fill="${INK}"/>
      <path d="M52 45 q3 -2 6 0 M62 45 q3 -2 6 0" stroke="${c.shade}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <path d="M57 50 q3 2 6 0 M59 50 v3 M61 50 v3" stroke="${c.shade}" stroke-width="1.3" fill="none"/>
      <path d="M53 56 Q60 62 67 56 Q60 60 53 56 Z" fill="${PINK}" stroke="${c.line}" stroke-width="1.2"/>
      ${eyes(54, 66, 46, 2.4, "#e9edf2")}
    </g>`,

  // ── Silverback — colossal shoulders with a bright silver back-saddle, tall crest, chest-beating fists ─
  silverback: (c) => `
    <g class="breathe">
      <path d="M24 98 Q22 62 46 58 Q60 56 74 58 Q98 62 96 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 70 Q60 60 90 70 Q88 82 60 84 Q32 82 30 70 Z" fill="${c.shade}" opacity=".9"/>
      <path d="M32 72 Q60 64 88 72" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".5"/>
    </g>
    <g class="tail-wag">
      ${mirror(`<path d="M42 62 Q26 72 40 88" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/><path d="M42 62 Q26 72 40 88" fill="none" stroke="${c.body}" stroke-width="8" stroke-linecap="round"/><circle cx="42" cy="86" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`)}
      <path d="M42 62 Q26 72 40 88" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round"/><path d="M42 62 Q26 72 40 88" fill="none" stroke="${c.body}" stroke-width="8" stroke-linecap="round"/><circle cx="42" cy="86" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="head-tilt">
      <path d="M50 24 Q60 12 70 24 Q66 20 60 20 Q54 20 50 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 42 Q44 20 60 20 Q76 20 76 42 Q76 60 60 60 Q44 60 44 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 44 Q48 34 60 34 Q72 34 72 46 Q72 58 60 60 Q48 58 48 44 Z" fill="${INK}"/>
      <path d="M50 40 q10 -4 20 0" stroke="${c.shade}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      <path d="M56 48 Q60 52 64 48 M58 48 v3 M62 48 v3" stroke="${c.shade}" stroke-width="1.6" fill="none"/>
      <path d="M53 54 Q60 60 67 54" stroke="${c.shade}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eyes(53, 67, 44, 2.6, "#e9edf2")}
    </g>`,

  // ── Bushbaby — clinging to a branch, saucer eyes, big round ears, fluffy curled tail ────────────
  bushbaby: (c) => `
    <path d="M84 14 Q78 60 82 106" fill="none" stroke="${BRANCH}" stroke-width="7" stroke-linecap="round"/>
    <g class="tail-wag">
      <path d="M56 82 Q34 92 34 70 Q36 58 48 62" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/>
      <path d="M56 82 Q34 92 34 70 Q36 58 48 62" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>
      ${pom(35, 66, 8, c.shade, c.line, 8, 2)}
    </g>
    <g class="breathe"><ellipse cx="58" cy="72" rx="15" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="58" cy="76" rx="8" ry="9" fill="${c.shade}" opacity=".5"/>
      <path d="M72 74 q10 -2 12 6 q-8 4 -12 -1 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      ${mirror(`<ellipse cx="48" cy="40" rx="8" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><ellipse cx="48" cy="40" rx="4" ry="5" fill="${c.shade}"/>`)}
      <ellipse cx="48" cy="40" rx="8" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><ellipse cx="48" cy="40" rx="4" ry="5" fill="${c.shade}"/>
      <circle cx="58" cy="48" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 40 v-4" stroke="${WHT}" stroke-width="2" opacity=".6" stroke-linecap="round"/>
      ${bigEye(52, 47, 6.5, AMBER, c.line)}
      ${bigEye(64, 47, 6.5, AMBER, c.line)}
      <path d="M56 54 L58 57 L60 54 Z" fill="${INK}"/>
    </g>`,
};

export const ROSTER_PRIMATES = [
  { n: "Orangutan",        e: "🦧", tier: 3, float: false },
  { n: "Gibbon",           e: "🐒", tier: 2, float: false },
  { n: "Baboon",           e: "🐒", tier: 2, float: false },
  { n: "Mandrill",         e: "🐵", tier: 3, float: false },
  { n: "Macaque",          e: "🐒", tier: 1, float: false },
  { n: "Ring-Tailed Lemur", e: "🐒", tier: 2, float: false },
  { n: "Tarsier",          e: "👀", tier: 3, float: false },
  { n: "Marmoset",         e: "🐒", tier: 1, float: false },
  { n: "Capuchin",         e: "🐵", tier: 1, float: false },
  { n: "Howler Monkey",    e: "🙊", tier: 2, float: false },
  { n: "Spider Monkey",    e: "🐒", tier: 2, float: false },
  { n: "Proboscis Monkey", e: "👃", tier: 3, float: false },
  { n: "Slow Loris",       e: "🐒", tier: 3, float: false },
  { n: "Galago",           e: "🐒", tier: 1, float: false },
  { n: "Gelada",           e: "🐒", tier: 3, float: false },
  { n: "Colobus",          e: "🐒", tier: 2, float: false },
  { n: "Langur",           e: "🐒", tier: 2, float: false },
  { n: "Bonobo",           e: "🐵", tier: 2, float: false },
  { n: "Silverback",       e: "🦍", tier: 3, float: false },
  { n: "Bushbaby",         e: "🐒", tier: 1, float: false },
];
