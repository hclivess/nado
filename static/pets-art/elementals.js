// pets-art/elementals.js — BESPOKE hand-drawn SVG art for ELEMENTALS (living-element spirit beasts, NADO Pets).
// Each entry: (c) => "<svg inner markup>" for viewBox 0 0 120 120, creature centered ~(60,62), within x,y ∈ [8,114].
// The MAIN MASS recolours from the coat `c`: c.body (main fill), c.shade (darker accent/underside), c.line (outline).
// Only universal element accents are fixed tints so the element always reads: fire #ff7a1a/#ffd24a, ice/air #bfe3ff,
// spark #7fe3ff, glow #eafff4, beaks/horns #f2c94c. Bellies/facets derive from the coat via belly/tint/deepen.
// Continuous-silhouette house style: ONE closed body path (c.body + rounded c.line stroke 3.2), appendages tucked
// behind, two-tone belly/shade shading, big glossy ceye faces, grounded with floorShadow.
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile } from "../pets-draw.js";

const FIRE = "#ff7a1a", FIRE2 = "#ffd24a", ICE = "#bfe3ff", SPARK = "#7fe3ff", GLOW = "#eafff4", BEAK = "#f2c94c";

// a little flame tongue: sharp point at top (cx, base-h), rounded bottom at (cx, base)
const flame = (cx, base, w, h, f) =>
  `<path d="M${cx} ${base - h} C${cx - w} ${base - h * 0.5} ${cx - w * 0.7} ${base} ${cx} ${base} C${cx + w * 0.7} ${base} ${cx + w} ${base - h * 0.5} ${cx} ${base - h} Z" fill="${f}"/>`;

export const ART_ELEMENTALS = {
  // ── Fire Elemental — a living flame body (coat) with orange/gold inner tongues, cute face on the glow (t3)
  fireelemental: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 26)}
    <g class="breathe">
      <path d="M60 12 C64 24 70 30 74 38 C78 30 80 26 79 20 C86 30 90 44 88 60 C88 88 76 104 60 104 C44 104 32 88 32 60 C31 46 34 34 40 26 C40 32 42 36 46 40 C49 32 55 24 60 12 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 78 C34 62 40 52 48 50 C42 60 44 76 52 86 C44 88 38 86 36 78 Z" fill="${c.shade}" opacity=".4"/>
      ${flame(60, 96, 15, 46, FIRE)}
      ${flame(60, 90, 9, 28, FIRE2)}
      ${ceye(51, 66, 4.2)}${ceye(69, 66, 4.2)}
      <path d="M60 72 l-3 3 h6 Z" fill="${INK}"/>
      ${smile(60, 76, 3.2)}
      <circle cx="45" cy="40" r="2.2" fill="${FIRE2}" opacity=".7"/>
    </g>`;
  },

  // ── Water Elemental — glossy droplet spirit with catchlight, ripple lines, blue-tint cheeks (t3)
  waterelemental: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 24)}
    <g class="breathe">
      <path d="M60 16 C70 38 86 54 86 76 C86 96 75 106 60 106 C45 106 34 96 34 76 C34 54 50 38 60 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 78 C44 62 50 54 58 52 C50 60 50 74 58 84 C50 86 46 84 44 78 Z" fill="${GLOW}" opacity=".5"/>
      <ellipse cx="60" cy="88" rx="20" ry="12" fill="${B}" opacity=".8"/>
      <ellipse cx="48" cy="50" rx="4" ry="6.5" fill="#fff" opacity=".6"/>
      <path d="M40 94 Q60 100 80 94" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5" stroke-linecap="round"/>
      ${ceye(52, 74, 4.2)}${ceye(68, 74, 4.2)}
      <path d="M54 84 Q60 89 66 84" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="46" cy="82" r="3" fill="${ICE}" opacity=".45"/><circle cx="74" cy="82" r="3" fill="${ICE}" opacity=".45"/>
    </g>`;
  },

  // ── Earth Elemental — angular jagged rock spirit, shard shoulders, rock arms, blocky feet, facet seams (t3)
  earthelemental: (c) => {
    const B = belly(c), S = c.shade;
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M32 62 L20 60 L16 74 L26 82 L36 76 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M88 62 L100 60 L104 74 L94 82 L84 76 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 54 L50 44 L72 46 L86 58 L88 92 L72 104 L48 104 L32 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 96 L36 108 L50 108 L48 98 Z M72 98 L70 108 L84 108 L80 96 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 34 l6 12 l-11 -2 Z M74 36 l-4 12 l11 -1 Z" fill="${S}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 46 L54 60 L44 66 M72 48 L68 62 L80 66 M54 60 L68 62" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".45"/>
      <ellipse cx="60" cy="76" rx="18" ry="13" fill="${B}"/>
      ${ceye(52, 72, 4)}${ceye(68, 72, 4)}
      <path d="M60 78 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      ${smile(60, 82, 3)}
      <circle cx="44" cy="52" r="2" fill="${GLOW}" opacity=".5"/><circle cx="78" cy="88" r="2.4" fill="${GLOW}" opacity=".45"/>
    </g>`;
  },

  // ── Air Elemental — floating wind puff with curling breeze tendrils & swirl bands (t3, float, swirly)
  airelemental: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 20)}
    <g class="tail-wag">
      ${tube("M56 82 C58 98 46 104 38 98 C31 93 34 84 42 84 C48 84 49 90 45 93", c.body, c.line, 7)}
      ${tube("M74 78 C86 84 92 78 90 70", c.shade, c.line, 6)}
    </g>
    <g class="breathe">
      <path d="M40 62 C34 50 42 40 52 42 C54 34 66 34 68 42 C80 40 86 52 80 62 C88 66 88 80 78 84 C80 92 70 96 62 90 C56 96 46 94 44 86 C34 84 32 70 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="17" ry="13" fill="${B}"/>
      <path d="M40 52 Q54 46 68 50 M36 64 Q46 60 56 64 M42 78 Q54 82 66 78" fill="none" stroke="${ICE}" stroke-width="2.4" stroke-linecap="round" opacity=".85"/>
      ${ceye(54, 64, 4.2)}${ceye(70, 64, 4.2)}
      <path d="M58 72 Q64 76 70 72" fill="none" stroke="${INK}" stroke-width="1.7" stroke-linecap="round"/>
      <circle cx="48" cy="46" r="2.4" fill="${GLOW}" opacity=".6"/>
    </g>`;
  },

  // ── Ice Elemental — crystalline hex-crystal spirit, facet seams, side shards, glints (t3, crystalline)
  iceelemental: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 24)}
    <g class="tail-wag">
      <path d="M34 60 L22 50 L28 68 Z M86 60 L98 50 L92 68 Z" fill="${ICE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M60 14 L72 40 L88 50 L82 82 L60 104 L38 82 L32 50 L48 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 14 L60 104 M32 50 L88 50 M48 40 L72 40" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".4"/>
      <path d="M60 40 L72 50 L60 62 L48 50 Z" fill="${B}"/>
      <path d="M40 66 L60 78 L80 66 L60 100 Z" fill="${ICE}" opacity=".35"/>
      <path d="M52 30 L60 16 L68 30 Z" fill="${GLOW}" opacity=".6"/>
      ${ceye(52, 60, 4)}${ceye(68, 60, 4)}
      <path d="M55 68 Q60 72 65 68" fill="none" stroke="${INK}" stroke-width="1.7" stroke-linecap="round"/>
      <circle cx="46" cy="70" r="2.2" fill="#fff" opacity=".7"/><circle cx="74" cy="56" r="1.8" fill="#fff" opacity=".7"/>
    </g>`;
  },

  // ── Lightning Elemental — jagged bolt-shaped body, spark accents, side mini-bolts (t4, jagged sparks)
  lightningelemental: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 24)}
    <g class="breathe">
      <path d="M60 12 L70 38 L62 40 L78 60 L66 60 L80 86 L60 106 L40 86 L54 60 L42 60 L58 40 L50 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="60" cy="70" r="14" fill="${B}"/>
      <path d="M64 20 L58 44 L66 46 L54 66" fill="none" stroke="${SPARK}" stroke-width="2.2" stroke-linecap="round" opacity=".85"/>
      ${ceye(53, 68, 4.2)}${ceye(67, 68, 4.2)}
      <path d="M60 74 l-2.6 3 h5.2 Z" fill="${INK}"/>
      ${smile(60, 78, 3)}
      <path d="M30 54 l8 4 l-6 3 l7 4 M90 54 l-8 4 l6 3 l-7 4" fill="none" stroke="${SPARK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>
    </g>`;
  },

  // ── Lava Golem — dark rocky golem (deepened coat) with glowing cracks, molten eyes & maw (t4, cracked glowing)
  lavagolem: (c) => {
    const B = belly(c), S = deepen(c.body, 0.28);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M32 60 L18 58 L14 74 L26 82 L36 74 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M88 60 L102 58 L106 74 L94 82 L84 74 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 52 L48 42 L74 44 L86 56 L88 92 L72 104 L48 104 L32 90 Z" fill="${S}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 96 L36 108 L50 108 L48 98 Z M72 98 L70 108 L84 108 L80 96 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 44 L48 62 L60 70 L54 88 M74 46 L70 58 L82 66 M60 50 L64 64 L58 70" fill="none" stroke="${FIRE}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M52 44 L48 62 L60 70 L54 88 M74 46 L70 58 L82 66" fill="none" stroke="${FIRE2}" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="40" cy="76" r="2" fill="${FIRE2}"/><circle cx="82" cy="72" r="2" fill="${FIRE2}"/>
      ${ceye(52, 66, 4)}${ceye(68, 66, 4)}
      <ellipse cx="52" cy="66" rx="4.8" ry="5.2" fill="none" stroke="${FIRE2}" stroke-width="1" opacity=".75"/><ellipse cx="68" cy="66" rx="4.8" ry="5.2" fill="none" stroke="${FIRE2}" stroke-width="1" opacity=".75"/>
      <path d="M50 78 Q60 85 70 78" fill="none" stroke="${FIRE}" stroke-width="2.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Storm Sprite — floating fluffy storm cloud with a bolt beneath & rain wisps (t3, float)
  stormsprite: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 20)}
    <g class="tail-wag">
      <path d="M54 84 L48 96 L57 94 L50 110 L66 92 L57 94 L63 84 Z" fill="${SPARK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${pom(60, 60, 26, c.body, c.line, 9, 3.2)}
      <ellipse cx="60" cy="66" rx="18" ry="11" fill="${B}"/>
      <path d="M40 74 Q42 82 38 88 M74 74 Q76 82 72 88" fill="none" stroke="${ICE}" stroke-width="2.2" stroke-linecap="round" opacity=".8"/>
      ${ceye(52, 58, 4.2)}${ceye(68, 58, 4.2)}
      <path d="M54 66 Q60 70 66 66" fill="none" stroke="${INK}" stroke-width="1.7" stroke-linecap="round"/>
      <circle cx="46" cy="52" r="3" fill="#fff" opacity=".5"/>
    </g>`;
  },

  // ── Frost Wraith — floating ghost with icicle-tattered hem, frosty aura, glowing icy eyes (t4, float)
  frostwraith: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 20)}
    <g class="tail-wag">
      <path d="M30 58 Q18 60 20 72 Q24 66 30 68 Z M90 58 Q102 60 100 72 Q96 66 90 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="58" rx="34" ry="30" fill="${ICE}" opacity=".2"/>
      <path d="M30 58 C30 30 90 30 90 58 L90 92 L82 82 L74 94 L66 82 L58 94 L50 82 L42 94 L34 82 L30 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M74 94 L72 104 M58 94 L56 104 M42 94 L40 104" stroke="${ICE}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="60" rx="20" ry="15" fill="${tint(c.body, 0.4)}" opacity=".7"/>
      <path d="M40 46 Q52 40 62 44" fill="none" stroke="${ICE}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
      ${ceye(52, 56, 4.4)}${ceye(68, 56, 4.4)}
      <ellipse cx="52" cy="56" rx="5" ry="5.6" fill="none" stroke="${ICE}" stroke-width="1.2" opacity=".85"/><ellipse cx="68" cy="56" rx="5" ry="5.6" fill="none" stroke="${ICE}" stroke-width="1.2" opacity=".85"/>
      <ellipse cx="60" cy="66" rx="4" ry="5" fill="${INK}" opacity=".6"/>
    </g>`;
  },

  // ── Ember Imp — little flame imp: horns, forked flame tail, belly-flame, mischievous grin (t2)
  emberimp: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 20)}
    <g class="tail-wag">
      <path d="M78 84 C94 84 96 70 90 62 C92 70 84 74 78 72 C86 78 82 84 78 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${flame(90, 64, 6, 17, FIRE)}
    </g>
    <g class="breathe">
      <path d="M60 40 C78 40 84 54 84 70 C84 90 74 98 60 98 C46 98 36 90 36 70 C36 54 42 40 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 32 L49 47 L38 44 Z M76 32 L71 47 L82 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="78" rx="17" ry="13" fill="${B}"/>
      ${flame(60, 88, 9, 20, FIRE)}
      ${flame(60, 84, 5, 12, FIRE2)}
      ${ceye(52, 66, 4.4)}${ceye(68, 66, 4.4)}
      <path d="M52 74 Q60 80 68 74 Q60 78 52 74 Z" fill="${INK}"/>
      <path d="M55 74 l1.6 3 l1.6 -3 Z" fill="#fff"/>
    </g>`;
  },

  // ── Tide Spirit — a cresting wave form, foam crest, ripple lines, face on the swell (t3, wave form)
  tidespirit: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 26)}
    <g class="breathe">
      <path d="M30 100 C24 74 30 44 58 42 C82 40 94 56 88 68 C84 60 74 56 68 62 C78 66 80 78 70 82 C78 84 78 96 68 98 C56 100 40 100 30 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 92 C30 72 34 52 56 50 C46 56 42 74 46 92 Z" fill="${B}" opacity=".7"/>
      ${pom(80, 52, 10, GLOW, c.line, 7, 1.6)}
      <path d="M40 68 Q54 62 66 68 M38 80 Q50 76 60 80" fill="none" stroke="${tint(c.body, 0.5)}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
      ${ceye(46, 72, 4.2)}${ceye(60, 72, 4.2)}
      <path d="M48 82 Q53 86 58 82" fill="none" stroke="${INK}" stroke-width="1.7" stroke-linecap="round"/>
      <circle cx="72" cy="46" r="2.4" fill="${GLOW}"/><circle cx="88" cy="58" r="2" fill="${GLOW}" opacity=".8"/>
    </g>`;
  },

  // ── Stone Guardian — a round mossy boulder with heavy brow, stubby rock arms, blocky feet (t3, boulder)
  stoneguardian: (c) => {
    const B = belly(c), S = c.shade;
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M30 70 L18 72 L18 88 L32 88 Z M90 70 L102 72 L102 88 L88 88 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 36 C86 36 96 56 94 78 C92 98 78 106 60 106 C42 106 28 98 26 78 C24 56 34 36 60 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 96 L32 108 L46 108 L46 98 Z M74 98 L74 108 L88 108 L86 96 Z" fill="${S}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 60 L44 58 M90 60 L76 58 M40 82 L52 86 M80 84 L70 88" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".4"/>
      <path d="M38 42 Q60 36 82 42 L80 52 Q60 46 40 52 Z" fill="${S}" opacity=".5"/>
      <ellipse cx="60" cy="80" rx="20" ry="13" fill="${B}"/>
      <path d="M44 64 Q52 60 58 64 M62 64 Q70 60 76 64" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
      ${ceye(52, 72, 4)}${ceye(68, 72, 4)}
      ${smile(60, 80, 3.4)}
      <circle cx="40" cy="66" r="2.2" fill="${GLOW}" opacity=".4"/>
    </g>`;
  },

  // ── Gale Djinn — a wind genie: torso with crossed arms & topknot, swirling wisp tail below (t4, float)
  galedjinn: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 22)}
    <g class="tail-wag">
      <path d="M46 78 C36 92 40 104 52 108 C46 100 48 92 54 88 C48 96 56 104 64 102 C58 98 60 90 66 88 C74 96 84 92 84 82 C78 86 70 84 66 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M50 96 Q56 100 62 96 M58 104 Q64 106 70 102" fill="none" stroke="${ICE}" stroke-width="1.8" stroke-linecap="round" opacity=".6"/>
    </g>
    <g class="breathe">
      <path d="M60 26 C74 26 84 36 84 50 C84 62 76 70 66 74 L54 74 C44 70 36 62 36 50 C36 36 46 26 60 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 56 C30 54 26 62 30 68 C34 62 40 64 44 68 Z M80 56 C90 54 94 62 90 68 C86 62 80 64 76 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 16 C56 20 58 26 60 28 C62 26 64 20 60 16 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="52" rx="18" ry="14" fill="${B}"/>
      ${ceye(52, 50, 4.4)}${ceye(68, 50, 4.4)}
      <path d="M60 56 l-2.6 3 h5.2 Z" fill="${INK}"/>
      <path d="M50 64 Q60 70 70 64" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M48 68 Q56 76 60 74 Q64 76 72 68" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M32 44 Q26 46 24 52 M88 44 Q94 46 96 52" fill="none" stroke="${ICE}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
    </g>`;
  },

  // ── Magma Beast — bulky lava-crusted quadruped with spiked ridge, molten cracks, fire maw (t4)
  magmabeast: (c) => {
    const B = belly(c), S = deepen(c.body, 0.28);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M86 84 C102 82 106 68 100 60 C102 70 92 74 84 74 Z" fill="${S}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${flame(101, 62, 6, 16, FIRE)}
    </g>
    <g class="breathe">
      <path d="M28 96 L30 78 C30 58 44 48 60 48 C76 48 90 58 90 78 L92 96 L80 96 L78 84 L66 96 L54 96 L42 84 L40 96 Z" fill="${S}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[44, 52, 60, 68].map(x => `<path d="M${x} 50 l4 -13 l4 13 Z" fill="${S}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`).join("")}
      <path d="M36 72 Q60 64 84 72 M40 60 L52 74 M80 60 L68 74 M60 56 L60 74" fill="none" stroke="${FIRE}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="18" ry="10" fill="${FIRE}" opacity=".28"/>
      ${ceye(50, 70, 4)}${ceye(70, 70, 4)}
      <ellipse cx="50" cy="70" rx="4.8" ry="5.2" fill="none" stroke="${FIRE2}" stroke-width="1" opacity=".75"/><ellipse cx="70" cy="70" rx="4.8" ry="5.2" fill="none" stroke="${FIRE2}" stroke-width="1" opacity=".75"/>
      <path d="M50 82 Q60 88 70 82" fill="none" stroke="${FIRE}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M52 83 l2 4 M60 84 l0 4 M68 83 l-2 4" stroke="${FIRE2}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Crystal Golem — faceted gem golem, gem-shard arms, crystal legs, glints (t4, gem body)
  crystalgolem: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M32 58 L20 64 L26 78 L36 72 Z M88 58 L100 64 L94 78 L84 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 36 L78 48 L84 74 L72 96 L48 96 L36 74 L42 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 90 L44 108 L54 108 L54 92 Z M66 92 L66 108 L76 108 L74 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 36 L60 96 M42 48 L84 74 M78 48 L36 74" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".35"/>
      <path d="M60 48 L74 58 L60 70 L46 58 Z" fill="${B}"/>
      <path d="M52 44 L60 38 L68 44 Z" fill="${GLOW}" opacity=".6"/>
      <path d="M64 74 L78 70 L72 88 Z" fill="${ICE}" opacity=".3"/>
      ${ceye(53, 58, 3.8)}${ceye(67, 58, 3.8)}
      ${smile(60, 64, 2.8)}
      <circle cx="48" cy="66" r="1.8" fill="#fff" opacity=".7"/><circle cx="72" cy="52" r="1.6" fill="#fff" opacity=".7"/>
    </g>`;
  },

  // ── Mist Phantom — soft diffuse ghost, wavy hem, misty aura, translucent, gentle face (t3, float)
  mistphantom: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 22)}
    <g class="tail-wag">
      <path d="M28 62 Q16 66 18 78 Q22 70 30 72 Z M92 62 Q104 66 102 78 Q98 70 90 72 Z" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".85"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="60" rx="36" ry="32" fill="${tint(c.body, 0.45)}" opacity=".25"/>
      <path d="M28 60 C28 32 92 32 92 60 L92 88 Q86 98 78 90 Q70 98 62 90 Q54 98 46 90 Q38 98 32 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".95"/>
      <ellipse cx="60" cy="62" rx="22" ry="16" fill="${tint(c.body, 0.4)}" opacity=".6"/>
      <path d="M38 48 Q54 42 68 46 M40 72 Q52 78 66 74" fill="none" stroke="${tint(c.body, 0.6)}" stroke-width="2.2" stroke-linecap="round" opacity=".6"/>
      ${ceye(52, 58, 4.4)}${ceye(70, 58, 4.4)}
      <ellipse cx="60" cy="70" rx="3.6" ry="4.6" fill="${INK}" opacity=".55"/>
      <circle cx="44" cy="46" r="2.6" fill="#fff" opacity=".4"/>
    </g>`;
  },

  // ── Cinder Hound — front-sitting hound with flame-tipped ears, fire mane & tail, glowing eyes (t3, flaming dog)
  cinderhound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M84 92 C100 88 102 72 94 64 C96 74 86 78 80 82 C88 84 86 92 84 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${flame(95, 66, 7, 18, FIRE)}${flame(95, 62, 4, 10, FIRE2)}
    </g>
    <g class="breathe">
      <path d="M60 108 C40 108 34 92 38 76 C40 66 44 60 48 56 L44 40 Q40 34 44 30 Q50 34 52 42 L56 52 Q60 50 64 52 L68 42 Q70 34 76 30 Q80 34 76 40 L72 56 C76 60 80 66 82 76 C86 92 80 108 60 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${flame(45, 34, 6, 15, FIRE)}${flame(75, 34, 6, 15, FIRE)}
      <path d="M40 54 Q60 46 80 54 Q60 50 40 54 Z" fill="${FIRE}" opacity=".5"/>
      <ellipse cx="60" cy="82" rx="18" ry="14" fill="${B}"/>
      ${ceye(51, 72, 4.2)}${ceye(69, 72, 4.2)}
      <path d="M60 78 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 81 v3 M60 84 q-4 3 -8 2 M60 84 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <ellipse cx="60" cy="84" rx="10" ry="6" fill="none" stroke="${FIRE2}" stroke-width="0.8" opacity=".5"/>
    </g>`;
  },

  // ── Thunder Roc — front-facing storm bird, spark-tipped wings, crest, gold beak, glowing eyes (t4, float)
  thunderroc: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag">
      <path d="M40 66 C18 56 8 66 10 80 C22 72 32 74 42 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M80 66 C102 56 112 66 110 80 C98 72 88 74 78 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M16 72 l6 2 l-4 4 M104 72 l-6 2 l4 4" fill="none" stroke="${SPARK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 30 C74 30 82 42 82 58 C82 82 72 98 60 98 C48 98 38 82 38 58 C38 42 46 30 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 92 L48 104 L56 100 M68 92 L72 104 L64 100" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <ellipse cx="60" cy="70" rx="16" ry="18" fill="${B}"/>
      <path d="M48 70 Q60 64 72 70 M50 80 Q60 76 70 80" fill="none" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round" opacity=".5"/>
      <path d="M60 44 L52 38 L60 32 L68 38 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${ceye(52, 50, 4.4)}${ceye(68, 50, 4.4)}
      <path d="M60 54 L54 60 L60 62 L66 60 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M40 44 l-6 -3 l4 6 M80 44 l6 -3 l-4 6" fill="none" stroke="${SPARK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Glacier Titan — huge blocky ice giant, shard shoulders, icy brow, icicle beard, glowing eyes (t5, ice giant)
  glaciertitan: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 32)}
    <g class="tail-wag">
      <path d="M30 56 L16 62 L14 84 L28 84 L34 66 Z M90 56 L104 62 L106 84 L92 84 L86 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M18 84 L16 96 M24 84 L24 96 M96 84 L96 96 M102 84 L104 96" stroke="${ICE}" stroke-width="2.4" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M32 52 L48 42 L72 42 L88 52 L86 96 L70 106 L50 106 L34 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.4" stroke-linejoin="round"/>
      <path d="M38 98 L36 110 L52 110 L52 100 Z M68 100 L68 110 L84 110 L82 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M34 46 L44 34 L44 48 Z M86 46 L76 34 L76 48 Z" fill="${ICE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 60 L60 56 L76 60 L74 78 L60 82 L46 78 Z" fill="${tint(c.body, 0.35)}"/>
      <path d="M50 60 L54 74 M70 60 L66 74 M60 56 L60 82" fill="none" stroke="${ICE}" stroke-width="1.4" opacity=".5"/>
      <path d="M42 54 Q52 50 58 54 M62 54 Q70 50 78 54" fill="none" stroke="${c.line}" stroke-width="2.8" stroke-linecap="round"/>
      ${ceye(52, 62, 4.4)}${ceye(68, 62, 4.4)}
      <ellipse cx="52" cy="62" rx="5" ry="5.4" fill="none" stroke="${ICE}" stroke-width="1.2" opacity=".75"/><ellipse cx="68" cy="62" rx="5" ry="5.4" fill="none" stroke="${ICE}" stroke-width="1.2" opacity=".75"/>
      <path d="M50 72 Q60 76 70 72" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M52 74 l0 8 M56 75 l0 9 M60 75 l0 10 M64 75 l0 9 M68 74 l0 8" stroke="${ICE}" stroke-width="1.6" stroke-linecap="round" opacity=".85"/>
    </g>`;
  },

  // ── Sand Wisp — little floating dust-devil: wide swirling funnel tapering to a point, grains (t2, float)
  sandwisp: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 15)}
    <g class="breathe">
      <path d="M34 36 Q60 26 86 36 C84 46 74 50 80 58 C72 64 66 62 70 70 C64 76 58 74 62 82 C60 90 62 96 60 102 C58 96 60 90 58 82 C52 74 46 76 50 70 C54 62 48 64 40 58 C46 50 36 46 34 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="42" rx="19" ry="10" fill="${B}"/>
      <path d="M40 54 Q54 50 68 54 M46 68 Q56 65 64 68 M52 80 Q58 78 62 80" fill="none" stroke="${tint(c.body, 0.5)}" stroke-width="1.8" stroke-linecap="round" opacity=".7"/>
      ${ceye(52, 40, 4)}${ceye(68, 40, 4)}
      <path d="M55 48 Q60 52 65 48" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="46" cy="58" r="1.3" fill="${deepen(c.body, 0.2)}"/><circle cx="72" cy="60" r="1.3" fill="${deepen(c.body, 0.2)}"/><circle cx="58" cy="88" r="1.1" fill="${deepen(c.body, 0.2)}"/>
    </g>`;
  },
};

export const ROSTER_ELEMENTALS = [
  { n: "Fire Elemental",      e: "🔥", tier: 3, float: false },
  { n: "Water Elemental",     e: "💧", tier: 3, float: false },
  { n: "Earth Elemental",     e: "🪨", tier: 3, float: false },
  { n: "Air Elemental",       e: "🌀", tier: 3, float: true },
  { n: "Ice Elemental",       e: "❄️", tier: 3, float: false },
  { n: "Lightning Elemental", e: "⚡", tier: 4, float: false },
  { n: "Lava Golem",          e: "🌋", tier: 4, float: false },
  { n: "Storm Sprite",        e: "⛈️", tier: 3, float: true },
  { n: "Frost Wraith",        e: "👻", tier: 4, float: true },
  { n: "Ember Imp",           e: "😈", tier: 2, float: false },
  { n: "Tide Spirit",         e: "🌊", tier: 3, float: false },
  { n: "Stone Guardian",      e: "🗿", tier: 3, float: false },
  { n: "Gale Djinn",          e: "🧞", tier: 4, float: true },
  { n: "Magma Beast",         e: "♨️", tier: 4, float: false },
  { n: "Crystal Golem",       e: "💎", tier: 4, float: false },
  { n: "Mist Phantom",        e: "🌫️", tier: 3, float: true },
  { n: "Cinder Hound",        e: "🐕", tier: 3, float: false },
  { n: "Thunder Roc",         e: "🦅", tier: 4, float: true },
  { n: "Glacier Titan",       e: "🧊", tier: 5, float: false },
  { n: "Sand Wisp",           e: "🏜️", tier: 2, float: true },
];
