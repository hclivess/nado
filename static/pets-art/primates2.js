// primates2.js — BESPOKE hand-drawn SVG art for PRIMATES2 (more monkeys & prosimians, NADO Pets).
// HOUSE STYLE: one continuous head+body silhouette, two-tone shading, cute glossy face, tucked limbs/tail.
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,64), within x,y ∈ [8,114].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside), c.line (outline stroke).
// Fixed identity accents allowed SPARINGLY for signature face/limb markings; body always from c.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// ── signature accent colours (used sparingly, never the whole body) ──────────────────────────
const WHT = "#fbf6ee";   // white mustache / beard / mantle / face mask
const RED = "#d24b3e";   // uakari bright-red bare face
const BLUE = "#6d93cf";  // snub-nosed blue bare face
const GOLD = "#f2c94c";  // golden mane / snub-nosed cape
const ORANGE = "#e0863a";// lion-tamarin mane / de brazza brow / patas rufous mask
const MAROON = "#96483a";// douc chestnut lower legs
const AMBER = "#d8a23c"; // big nocturnal iris (potto / owl monkey)
const PINK = "#e79a9a";  // lips
const DARK = "#2b2f36";  // signature black bare face (drill / colobus / indri / mangabey)

const P = (n) => Number(n).toFixed(1);

// fused head+body sitting silhouette — ONE closed path. hw=head half-width, bw=body half-width.
const peanut = (c, hw = 26, bw = 28) => {
  const hl = 60 - hw, hr = 60 + hw, bl = 60 - bw, br = 60 + bw, wl = 60 - (hw - 4), wr = 60 + (hw - 4);
  return `<path d="M60 116 C${P(bl)} 116 ${P(bl - 2)} 100 ${P(bl + 2)} 84 C${P(bl + 8)} 74 ${P(wl - 2)} 70 ${P(wl)} 66 C${P(hl - 2)} 60 ${P(hl)} 50 ${P(hl)} 42 C${P(hl)} 27 ${P(hl + 11)} 19 60 19 C${P(hr - 11)} 19 ${P(hr)} 27 ${P(hr)} 42 C${P(hr)} 50 ${P(hr + 2)} 60 ${P(wr)} 66 C${P(wr + 2)} 70 ${P(br - 8)} 74 ${P(br - 2)} 84 C${P(br + 2)} 100 ${P(br)} 116 60 116 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;
};
// small rounded ears that overlap the head crown (left drawn + mirrored)
const ears = (c, ex = 38, ey = 30, er = 7) => { const e = `<circle cx="${ex}" cy="${ey}" r="${er}" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/><circle cx="${ex + 1}" cy="${ey + 1}" r="${(er * 0.45).toFixed(1)}" fill="${c.shade}"/>`; return mirror(e) + e; };
// two little seated feet peeking at the base
const feet = (c) => { const f = `<ellipse cx="46" cy="112" rx="9" ry="5.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>`; return mirror(f) + f; };
// folded hands resting on the belly
const hands = (c) => `<path d="M49 90 Q60 84 71 90 Q69 100 60 100 Q51 100 49 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`;
// a long tail that curls up the right side (rooted well inside the body)
const tail = (fill, line) => `<path d="M74 98 Q102 98 99 68 Q98 54 85 57 Q95 66 90 80 Q83 93 72 92 Z" fill="${fill}" stroke="${line}" stroke-width="3.2" stroke-linejoin="round"/>`;
const nose = (x = 60, y = 50) => `<path d="M${x} ${y} l-3 3.2 h6 Z" fill="${INK}"/>`;
// huge glossy nocturnal eye
const bigEye = (x, y, r, line) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${line}" stroke-width="1.8"/><circle cx="${x}" cy="${y}" r="${(r * 0.6).toFixed(1)}" fill="${AMBER}"/><circle cx="${x}" cy="${y}" r="${(r * 0.3).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.28).toFixed(1)}" cy="${(y - r * 0.3).toFixed(1)}" r="${(r * 0.16).toFixed(1)}" fill="#fff"/>`;
// white-scleraed eye for dark faces (so eyes never vanish)
const wEye = (x, y, r = 4) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${INK}" stroke-width="1.4"/><circle cx="${x}" cy="${y}" r="${(r * 0.55).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.3).toFixed(1)}" r="${(r * 0.22).toFixed(1)}" fill="#fff"/>`;

export const ART_PRIMATES2 = {
  // ── Emperor Tamarin — the long, drooping WHITE handlebar mustache ────────────────────────────
  emperortamarin: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 23, 25)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${ears(c, 40, 32, 6)}
      <ellipse cx="60" cy="45" rx="13" ry="14" fill="${B}"/>
      ${ceye(52, 41, 4)}${ceye(68, 41, 4)}
      ${nose(60, 49)}
      <path d="M58 51 Q42 50 33 66 Q46 58 57 56 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M62 51 Q78 50 87 66 Q74 58 63 56 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M56 53 Q60 57 64 53" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Golden Lion Tamarin — silky flowing MANE ringing a tiny bare face ────────────────────────
  goldenliontamarin: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 23, 25)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${pom(60, 42, 25, ORANGE, c.line, 17, 2.4)}
      <ellipse cx="60" cy="45" rx="12" ry="13" fill="${deepen(ORANGE, 0.28)}" stroke="${c.line}" stroke-width="1.8"/>
      ${ceye(53, 42, 3.8)}${ceye(67, 42, 3.8)}
      ${nose(60, 50)}
      ${smile(60, 53, 3.2)}
    </g>`; },

  // ── Squirrel Monkey — bold WHITE face mask with dark cap & muzzle ────────────────────────────
  squirrelmonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 26)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 22, 24)}
      <ellipse cx="60" cy="94" rx="12" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${ears(c, 40, 32, 5.5)}
      <path d="M42 44 Q42 28 60 28 Q78 28 78 44 Q78 50 74 54 Q68 40 60 40 Q52 40 46 54 Q42 50 42 44 Z" fill="${deepen(c.body, 0.45)}"/>
      <ellipse cx="60" cy="55" rx="8" ry="6.5" fill="${deepen(c.body, 0.45)}"/>
      <path d="M43 47 Q43 37 51 35 Q58 40 58 48 Q52 53 43 47 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M77 47 Q77 37 69 35 Q62 40 62 48 Q68 53 77 47 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      ${ceye(51, 44, 3.8)}${ceye(69, 44, 3.8)}
      <path d="M60 51 l-2.4 2.8 h4.8 Z" fill="${INK}"/>
      <path d="M55 57 Q60 60 65 57" stroke="${WHT}" stroke-width="1.3" fill="none" stroke-linecap="round" opacity=".6"/>
    </g>`; },

  // ── Titi Monkey — fuzzy, plump, pale forehead band & chest blaze ─────────────────────────────
  titimonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 25, 27)}
      <path d="M60 78 Q52 92 60 104 Q68 92 60 78 Z" fill="${B}" opacity=".9"/>
      ${feet(c)}${hands(c)}
      ${ears(c, 39, 33, 6)}
      <ellipse cx="60" cy="46" rx="14" ry="14" fill="${B}"/>
      <path d="M47 36 Q60 30 73 36" stroke="${WHT}" stroke-width="3" fill="none" stroke-linecap="round" opacity=".9"/>
      ${ceye(52, 44, 4)}${ceye(68, 44, 4)}
      ${nose(60, 51)}
      ${smile(60, 54, 3.4)}
    </g>`; },

  // ── Saki Monkey — thick fluffy HOOD of fur framing a pale bare face ──────────────────────────
  sakimonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag"><path d="M72 100 Q100 100 98 74 Q97 62 86 65 Q94 72 90 84 Q84 96 72 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${peanut(c, 26, 28)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${pom(60, 42, 26, c.body, c.line, 18, 2.6)}
      <ellipse cx="60" cy="46" rx="13" ry="14" fill="${tint(c.body, 0.55)}" stroke="${c.line}" stroke-width="1.6"/>
      ${ceye(53, 43, 3.6)}${ceye(67, 43, 3.6)}
      ${nose(60, 51)}
      <path d="M55 55 Q60 58 65 55" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Bald Uakari — startling bright-RED bald face, shaggy coat, stubby tail ───────────────────
  balduakari: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M78 100 Q94 100 92 88 Q88 92 78 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${peanut(c, 25, 31)}
      <path d="M34 74 q-3 8 -1 16 M86 74 q3 8 1 16 M40 96 l-2 8 M80 96 l2 8" stroke="${c.line}" stroke-width="1.5" fill="none" stroke-linecap="round" opacity=".5"/>
      <ellipse cx="60" cy="94" rx="15" ry="12" fill="${B}" opacity=".8"/>
      ${feet(c)}${hands(c)}
      <path d="M42 44 Q42 24 60 24 Q78 24 78 44 Q78 58 60 60 Q42 58 42 44 Z" fill="${RED}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 30 Q60 24 74 30" stroke="${tint(RED, 0.3)}" stroke-width="2" fill="none" stroke-linecap="round" opacity=".7"/>
      <path d="M50 40 q4 -2 7 0 M63 40 q4 -2 7 0" stroke="${deepen(RED, 0.35)}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      ${ceye(53, 44, 3.6)}${ceye(67, 44, 3.6)}
      <path d="M60 48 l-2.4 2.6 h4.8 Z" fill="${deepen(RED, 0.4)}"/>
      <path d="M54 54 Q60 58 66 54" stroke="${deepen(RED, 0.4)}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Douc Langur — the "costumed ape": grey body, chestnut socks, white forearms, golden face ─
  douclangur: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag"><path d="M74 98 Q102 98 99 68 Q98 54 85 57 Q95 66 90 80 Q83 93 72 92 Z" fill="${WHT}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${peanut(c, 24, 27)}
      <path d="M44 104 Q42 112 50 113 L52 100 Z" fill="${MAROON}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M76 104 Q78 112 70 113 L68 100 Z" fill="${MAROON}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 78 Q34 92 40 100 Q46 92 46 82 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 78 Q86 92 80 100 Q74 92 74 82 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="93" rx="12" ry="11" fill="${B}" opacity=".8"/>
      <path d="M42 44 Q42 26 60 26 Q78 26 78 44 Q78 58 60 60 Q42 58 42 44 Z" fill="${tint(ORANGE, 0.35)}" stroke="${c.line}" stroke-width="2"/>
      <path d="M42 50 Q30 54 34 64 Q42 58 46 54 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M78 50 Q90 54 86 64 Q78 58 74 54 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${ceye(53, 43, 3.6)}${ceye(67, 43, 3.6)}
      ${nose(60, 49)}
      <path d="M55 53 Q60 56 65 53" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Golden Snub-nosed Monkey — pale-BLUE bare face, upturned snub nose, golden cape ──────────
  goldensnubnosedmonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 25, 28)}
      ${pom(60, 40, 25, GOLD, c.line, 16, 2.4)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      <path d="M45 44 Q45 26 60 26 Q75 26 75 44 Q75 56 60 58 Q45 56 45 44 Z" fill="${BLUE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 34 q7 -3 14 -1 M58 34 q7 -3 14 1" stroke="${GOLD}" stroke-width="2.2" fill="none" stroke-linecap="round" opacity=".8"/>
      ${ceye(52, 42, 3.8)}${ceye(68, 42, 3.8)}
      <path d="M55 49 Q60 46 65 49 Q63 53 60 53 Q57 53 55 49 Z" fill="${deepen(BLUE, 0.3)}"/>
      <ellipse cx="57" cy="50" rx="1" ry="0.8" fill="${INK}"/><ellipse cx="63" cy="50" rx="1" ry="0.8" fill="${INK}"/>
      <path d="M53 55 Q60 59 67 55" stroke="${deepen(BLUE, 0.35)}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Vervet — black face ringed by a pale brow band & white cheek tufts ───────────────────────
  vervet: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 23, 26)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${ears(c, 39, 32, 6)}
      <path d="M32 44 Q40 40 44 46 Q40 50 34 50 Z" fill="${B}"/>
      <path d="M88 44 Q80 40 76 46 Q80 50 86 50 Z" fill="${B}"/>
      <ellipse cx="60" cy="46" rx="14" ry="14" fill="${DARK}"/>
      <path d="M46 37 Q60 31 74 37" stroke="${tint(c.body, 0.5)}" stroke-width="3.2" fill="none" stroke-linecap="round"/>
      ${wEye(53, 45, 3.6)}${wEye(67, 45, 3.6)}
      <path d="M60 50 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M54 55 Q60 58 66 55" stroke="${tint(c.body, 0.4)}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Patas Monkey — the greyhound of monkeys: very LONG limbs, white lower face ────────────────
  patasmonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 26)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    ${tube("M46 70 Q30 84 30 106", c.body, c.line, 6)}
    ${tube("M74 70 Q90 84 90 106", c.body, c.line, 6)}
    <g class="breathe">
      ${peanut(c, 21, 21)}
      <ellipse cx="60" cy="92" rx="11" ry="12" fill="${B}" opacity=".85"/>
      ${tube("M50 78 Q40 92 42 104", c.body, c.line, 5)}
      ${tube("M70 78 Q80 92 78 104", c.body, c.line, 5)}
      ${ears(c, 42, 32, 5.5)}
      <path d="M60 22 Q52 24 50 34" stroke="${deepen(c.body, 0.3)}" stroke-width="3" fill="none" stroke-linecap="round" opacity=".6"/>
      <ellipse cx="60" cy="47" rx="12" ry="13" fill="${tint(ORANGE, 0.25)}"/>
      <path d="M48 52 Q48 62 60 64 Q72 62 72 52 Q60 56 48 52 Z" fill="${WHT}"/>
      ${ceye(53, 44, 3.6)}${ceye(67, 44, 3.6)}
      <path d="M60 50 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M55 57 Q60 60 65 57" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Mangabey — dark face with bright pale UPPER EYELIDS & a peaked crest ─────────────────────
  mangabey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 24, 27)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      <path d="M50 24 Q60 12 70 24 Q64 20 60 20 Q56 20 50 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${ears(c, 40, 34, 5.5)}
      <ellipse cx="60" cy="46" rx="14" ry="14" fill="${DARK}"/>
      <path d="M47 41 Q52 37 58 40 Q52 43 47 43 Z" fill="${WHT}"/>
      <path d="M73 41 Q68 37 62 40 Q68 43 73 43 Z" fill="${WHT}"/>
      ${wEye(53, 45, 3.4)}${wEye(67, 45, 3.4)}
      <path d="M60 50 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M54 55 Q60 58 66 55" stroke="${tint(c.body, 0.4)}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Drill — glossy jet-black bare face, red lip, pale chin ruff, stocky ──────────────────────
  drill: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M78 100 Q94 100 92 88 Q88 92 78 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${peanut(c, 26, 31)}
      <ellipse cx="60" cy="94" rx="15" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${pom(60, 44, 24, tint(c.body, 0.25), c.line, 15, 2.4)}
      <path d="M45 44 Q45 26 60 26 Q75 26 75 44 Q75 60 60 62 Q45 60 45 44 Z" fill="${DARK}" stroke="${c.line}" stroke-width="2"/>
      <path d="M50 34 Q60 30 70 34" stroke="#4a5058" stroke-width="2" fill="none" stroke-linecap="round" opacity=".7"/>
      <path d="M56 40 v14 M64 40 v14" stroke="#4a5058" stroke-width="1.6" opacity=".5"/>
      ${wEye(53, 43, 3.4)}${wEye(67, 43, 3.4)}
      <path d="M53 56 Q60 60 67 56 Q60 62 53 56 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.2"/>
    </g>`; },

  // ── Sifaka — upright vertical-clinging LEAPER, arms flung up, long tail hanging ──────────────
  sifaka: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 22)}
    <g class="tail-wag">${tube("M70 66 Q92 82 86 112", c.body, c.line, 6)}</g>
    ${tube("M48 62 Q34 46 30 30", c.body, c.line, 5.5)}
    ${tube("M72 62 Q86 46 90 30", c.body, c.line, 5.5)}
    <g class="breathe">
      <path d="M60 110 C46 110 42 94 44 76 C45 62 51 54 60 54 C69 54 75 62 76 76 C78 94 74 110 60 110 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="11" ry="15" fill="${B}" opacity=".85"/>
      ${tube("M52 96 Q46 106 48 114", c.body, c.line, 5)}
      ${tube("M68 96 Q74 106 72 114", c.body, c.line, 5)}
      <circle cx="60" cy="40" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M45 38 Q45 24 60 24 Q75 24 75 38 Q68 32 60 32 Q52 32 45 38 Z" fill="${deepen(c.body, 0.35)}"/>
      <ellipse cx="60" cy="44" rx="11" ry="10" fill="${B}"/>
      ${ceye(53, 42, 3.6)}${ceye(67, 42, 3.6)}
      <path d="M60 46 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M55 51 Q60 54 65 51" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Indri — the largest lemur: TAILLESS, big tufted round ears, black-and-white ──────────────
  indri: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 26)}
    <g class="breathe">
      <path d="M60 112 C44 112 38 94 40 72 C42 52 51 42 60 42 C69 42 78 52 80 72 C82 94 76 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="14" ry="18" fill="${B}" opacity=".9"/>
      <path d="M46 100 Q44 110 52 112 L54 98 Z" fill="${deepen(c.body, 0.3)}"/>
      <path d="M74 100 Q76 110 68 112 L66 98 Z" fill="${deepen(c.body, 0.3)}"/>
      ${pom(38, 34, 10, c.body, c.line, 9, 2.4)}${pom(82, 34, 10, c.body, c.line, 9, 2.4)}
      <ellipse cx="60" cy="46" rx="15" ry="15" fill="${DARK}"/>
      <path d="M47 40 Q47 34 54 32 Q59 40 59 46 Q52 48 47 40 Z" fill="${B}"/>
      <path d="M73 40 Q73 34 66 32 Q61 40 61 46 Q68 48 73 40 Z" fill="${B}"/>
      ${wEye(53, 44, 3.6)}${wEye(67, 44, 3.6)}
      <path d="M60 49 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M55 54 Q60 57 65 54" stroke="${tint(c.body, 0.4)}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Potto — slow nocturnal clinger: enormous round eyes, tiny ears, gripping a branch ────────
  potto: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="breathe">
      ${peanut(c, 26, 27)}
      <ellipse cx="60" cy="92" rx="14" ry="13" fill="${B}" opacity=".8"/>
      <path d="M72 88 q12 -2 14 6 q-8 5 -14 -1 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 88 q-12 -2 -14 6 q8 5 14 -1 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${ears(c, 44, 30, 4.5)}
      <ellipse cx="60" cy="46" rx="14" ry="14" fill="${B}"/>
      <path d="M60 32 L57 52 L63 52 Z" fill="${c.shade}" opacity=".6"/>
      ${bigEye(51, 45, 8, c.line)}${bigEye(69, 45, 8, c.line)}
      <path d="M60 52 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M56 57 q4 2 8 0" stroke="${INK}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Woolly Monkey — dense woolly coat, dark round head, thick curled prehensile tail ─────────
  woollymonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag"><path d="M74 96 Q104 96 100 66 Q98 50 82 54 Q95 62 90 80 Q84 94 72 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="4" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${pom(60, 84, 28, c.body, c.line, 16, 3)}
      <ellipse cx="60" cy="90" rx="14" ry="12" fill="${B}" opacity=".8"/>
      ${feet(c)}${hands(c)}
      ${pom(60, 44, 22, c.body, c.line, 14, 2.6)}
      <ellipse cx="60" cy="46" rx="13" ry="13" fill="${deepen(c.body, 0.35)}"/>
      ${wEye(53, 43, 3.4)}${wEye(67, 43, 3.4)}
      <path d="M60 49 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M55 54 Q60 57 65 54" stroke="${tint(c.body, 0.35)}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── Guereza Colobus — sweeping white U-shaped MANTLE & bushy white tail tuft, black face ─────
  guerezacolobus: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 29)}
    <g class="tail-wag"><path d="M80 96 Q100 92 98 68" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/><path d="M80 96 Q100 92 98 68" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/>${pom(98, 60, 11, WHT, c.line, 10, 2.2)}</g>
    <g class="breathe">
      ${peanut(c, 25, 28)}
      <path d="M40 60 Q22 78 34 108 Q40 90 46 74 Q42 66 40 60 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M80 60 Q98 78 86 108 Q80 90 74 74 Q78 66 80 60 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 70 Q60 100 76 70 Q70 92 60 92 Q50 92 44 70 Z" fill="${WHT}" opacity=".9"/>
      ${feet(c)}
      <ellipse cx="60" cy="46" rx="15" ry="15" fill="${DARK}"/>
      <path d="M45 44 Q46 32 54 30 Q58 40 58 46 Q51 50 45 44 Z" fill="${tint(c.body, 0.5)}" opacity=".55"/>
      <path d="M75 44 Q74 32 66 30 Q62 40 62 46 Q69 50 75 44 Z" fill="${tint(c.body, 0.5)}" opacity=".55"/>
      ${wEye(53, 45, 3.6)}${wEye(67, 45, 3.6)}
      <path d="M60 49 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M54 54 Q60 57 66 54" stroke="${WHT}" stroke-width="1.5" fill="none" stroke-linecap="round" opacity=".7"/>
    </g>`; },

  // ── Talapoin — smallest African monkey: big round head, tiny body, alert ─────────────────────
  talapoin: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 22)}
    <g class="tail-wag"><path d="M70 96 Q92 96 90 74 Q89 64 80 66 Q86 72 83 82 Q78 92 68 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 108 C46 108 40 98 42 86 C43 78 48 74 54 72 C42 68 36 52 38 40 C40 24 49 18 60 18 C71 18 80 24 82 40 C84 52 78 68 66 72 C72 74 77 78 78 86 C80 98 74 108 60 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="10" ry="9" fill="${B}" opacity=".85"/>
      ${ears(c, 40, 34, 5.5)}
      <ellipse cx="60" cy="44" rx="15" ry="15" fill="${deepen(c.body, 0.28)}"/>
      <path d="M50 52 Q50 62 60 64 Q70 62 70 52 Q60 56 50 52 Z" fill="${tint(c.body, 0.5)}"/>
      ${ceye(52, 42, 4.4)}${ceye(68, 42, 4.4)}
      <path d="M60 49 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M55 55 Q60 58 65 55" stroke="${tint(c.body, 0.4)}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`; },

  // ── De Brazza's Monkey — orange diadem BROW, white nose-spot & big white BEARD ───────────────
  debrazzasmonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 25, 28)}
      <ellipse cx="60" cy="94" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}
      <path d="M40 88 Q36 78 40 70 L46 74 Q44 82 46 90 Z" fill="${WHT}" opacity=".85"/>
      <path d="M80 88 Q84 78 80 70 L74 74 Q76 82 74 90 Z" fill="${WHT}" opacity=".85"/>
      <ellipse cx="60" cy="46" rx="15" ry="15" fill="${DARK}"/>
      <path d="M47 36 Q60 28 73 36 Q60 33 47 36 Z" fill="${ORANGE}" stroke="${c.line}" stroke-width="1.2"/>
      <ellipse cx="60" cy="50" rx="4" ry="3" fill="${WHT}"/>
      <path d="M48 56 Q60 82 72 56 Q66 70 60 70 Q54 70 48 56 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${wEye(53, 44, 3.4)}${wEye(67, 44, 3.4)}
      <path d="M57 51 L60 54 L63 51 Z" fill="${INK}"/>
    </g>`; },

  // ── Owl Monkey — the only nocturnal monkey: HUGE eyes, three dark face stripes ───────────────
  owlmonkey: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag">${tail(c.shade, c.line)}</g>
    <g class="breathe">
      ${peanut(c, 25, 26)}
      <ellipse cx="60" cy="93" rx="13" ry="12" fill="${B}" opacity=".85"/>
      ${feet(c)}${hands(c)}
      ${ears(c, 43, 31, 4.5)}
      <ellipse cx="60" cy="46" rx="15" ry="14" fill="${tint(c.body, 0.5)}"/>
      <path d="M60 32 L57 56 L63 56 Z" fill="${deepen(c.body, 0.35)}"/>
      <path d="M46 34 Q49 46 52 52 Q48 46 44 40 Z" fill="${deepen(c.body, 0.35)}"/>
      <path d="M74 34 Q71 46 68 52 Q72 46 76 40 Z" fill="${deepen(c.body, 0.35)}"/>
      ${bigEye(51, 45, 8, c.line)}${bigEye(69, 45, 8, c.line)}
      <path d="M60 53 l-2.4 2.6 h4.8 Z" fill="${INK}"/>
      <path d="M56 58 q4 2 8 0" stroke="${INK}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
    </g>`; },
};

export const ROSTER_PRIMATES2 = [
  { n: "Emperor Tamarin",          e: "🐒", tier: 2, float: false },
  { n: "Golden Lion Tamarin",      e: "🐒", tier: 2, float: false },
  { n: "Squirrel Monkey",          e: "🐒", tier: 1, float: false },
  { n: "Titi Monkey",              e: "🐒", tier: 1, float: false },
  { n: "Saki Monkey",              e: "🐵", tier: 2, float: false },
  { n: "Bald Uakari",              e: "🐵", tier: 2, float: false },
  { n: "Douc Langur",              e: "🐒", tier: 2, float: false },
  { n: "Golden Snub-nosed Monkey", e: "🐵", tier: 3, float: false },
  { n: "Vervet",                   e: "🐒", tier: 1, float: false },
  { n: "Patas Monkey",             e: "🐒", tier: 2, float: false },
  { n: "Mangabey",                 e: "🐒", tier: 1, float: false },
  { n: "Drill",                    e: "🐵", tier: 2, float: false },
  { n: "Sifaka",                   e: "🐒", tier: 2, float: false },
  { n: "Indri",                    e: "🐒", tier: 2, float: false },
  { n: "Potto",                    e: "🐒", tier: 2, float: false },
  { n: "Woolly Monkey",            e: "🐒", tier: 2, float: false },
  { n: "Guereza Colobus",          e: "🐒", tier: 2, float: false },
  { n: "Talapoin",                 e: "🐒", tier: 1, float: false },
  { n: "De Brazza's Monkey",       e: "🐵", tier: 2, float: false },
  { n: "Owl Monkey",               e: "🐵", tier: 1, float: false },
];
