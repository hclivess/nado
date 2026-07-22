// autogame-art.js — the March's entire sprite world, drawn from nothing but ctx.fillRect.
//
// GROUND-UP REBUILD, second generation. Nothing survives from the first art file: new figure, new
// palettes, new poses, new monsters, new props, new gore. What DID survive is the contract with the
// renderer — export names, cell sizes, frame indices — so the game shell never had to learn anything.
//
// The world in one paragraph: a lone WAYFARER walks a chain-rolled road through five REALMS (the biome a
// leg wears is rolled by the same terrain hash its tiles are — see autogame-engine.js/biomeFor). Every
// realm keeps its own bestiary: 3 contract families × 2 ranks of local species, plus one realm BOSS, plus
// the MIMIC that follows the treasure everywhere — 36 creatures, every one with a breath loop, a wind-up,
// a strike, a crumple and a corpse. Seventeen non-combat tiles get standing PROPS with four-frame loops.
//
// Discipline (unchanged in spirit, rewritten in fact):
//   * ONE primitive — an integer rect. No paths, no gradients, no alpha, no anti-aliasing. Translucency
//     is a checkerboard, a curve is a stair, a glow is a brighter pixel.
//   * DETERMINISTIC — same opts, same pixels. No clocks, no randomness; every flicker is a table lookup
//     indexed by frame. A seed, where accepted, is folded through an integer hash.
//   * AUTHORED AT NATIVE RESOLUTION — the warrior lives in a 64×64 cell, everything else in 96×96. There
//     is no coarse grid and no doubling pen: what you write is what blits.
//   * SILHOUETTE FIRST — every mass is an outlined shape before it is a shaded one; rank changes the
//     DRAWING, never a scale factor.

import { unpackItem as unpackRaw } from "./autogame-engine.js?v=eb6129b3";

// ── cells ────────────────────────────────────────────────────────────────────────────────
export const FRAME_W = 64;
export const FRAME_H = 64;
const W_GROUND = 60;        // warrior: the row the contact shadow lies on; soles end on 59

const MW = 96, MH = 96;     // the world box: monsters, props, blood, fatalities all share it
const MCX = 48;
const MFOOT = 89;           // last row feet may occupy
const MGROUND = 91;         // the shadow row
export { MW as MON_W, MH as MON_H, MCX as MON_CX, MFOOT as MON_FOOT_Y, MGROUND as MON_GROUND_Y,
         MW as PROP_W, MH as PROP_H, MW as BLOOD_W, MH as BLOOD_H, MW as FAT_W, MH as FAT_H };

export const SLOTS = ["weapon", "helm", "body", "shield", "boots", "cloak"];
export const WALK_FRAMES = 4;            // reach → plant → cross → drive
export const ATTACK_FRAMES = 3;          // raise → cleave → carry-through
export const WARRIOR_ATTACK_FRAMES = 3;
export const WARRIOR_HIT_FRAMES = 1;

export const MON_IDLE_FRAMES = 3;        // 0,1,2 breath loop
export const MON_ATTACK_FRAME = 3;       // wind-up
export const MON_STRIKE_FRAME = 4;       // the blow lands
export const MON_ATTACK_FRAMES = 2;
export const MON_CRUMPLE_FRAME = 5;      // knees gone, light going out
export const MON_DEATH_FRAME = 6;        // the heap
export const MON_DEATH_FRAMES = 2;
export const MON_FRAMES = 7;

export const FAMILY_NAMES = ["grunt", "brute", "cannon"];
export const MON_RANK_NAMES = ["normal", "elite", "boss"];
export const BIOMES = 5;
export const BIOME_NAMES = ["greenwood", "fen", "crags", "ashway", "nether"];

export const PROP_FRAMES = 4;            // every prop breathes on a four-count
export const PROP_KINDS = ["hazard", "snare", "quag", "gale", "tollgate", "cache", "barrow", "armory",
                           "vein", "grove", "shrine", "well", "camp", "idol", "pyre", "forge", "fork",
                           "relic"];

// ── ramps ────────────────────────────────────────────────────────────────────────────────
// Five stops per ramp: o outline · d deep · m mid · l lit · s spark. The spark stop is new in this
// generation: one near-white accent per material is what lets a sprite glint without a glow filter.
const ramp = (o, d, m, l, s) => ({ o, d, m, l, s });

// Equipment materials — a fresh octave. Hues chosen so neighbouring tiers of different material never
// blur together at fight distance: umber → ash-blue → polished steel → moonsilver → voidglass → sunmetal
// → starfall violet → verdant.
// LOW KEY ON PURPOSE. The first draft of this rebuild ran the ramps bright and warm and the figure read
// as a cartoon; this game is a man walking a road that kills him, and the light behaves accordingly:
// near-black outlines, masses that sit in shadow, and the spark stop reserved for the few points of light
// (an edge, an ember, an eye) that carry the whole silhouette. Rarity still reads — by hue and by those
// sparks — but nothing glows that hasn't earned it.
export const MATERIALS = [
  ramp("#140b04", "#3f2812", "#5f3d1c", "#82562a", "#ab7a42"), // 0 bronze — old blood and dirt
  ramp("#0b0c10", "#23262e", "#3a3e4a", "#545968", "#767c8e"), // 1 iron — grave-cold
  ramp("#0c1014", "#2b343e", "#46545f", "#66798a", "#8fa5b5"), // 2 steel — a dull edge that still cuts
  ramp("#14161c", "#3e4450", "#636b7a", "#8c94a5", "#c2c9d6"), // 3 silver — moonlight on a blade
  ramp("#050308", "#16111f", "#292234", "#3f3650", "#5c527a"), // 4 obsidian — the dark that drinks light
  ramp("#1c1002", "#4c350c", "#7a5716", "#a87c24", "#d4a83c"), // 5 gold — tarnished, not gaudy
  ramp("#0c0716", "#251739", "#3d2a5c", "#5a4384", "#8064b2"), // 6 meteoric — bruise-violet
  ramp("#060f04", "#1c3410", "#31541c", "#4c7a2c", "#71a444"), // 7 living — moss in a crypt
];
export const MATERIAL_NAMES = ["bronze", "iron", "steel", "silver", "obsidian", "gold", "meteoric", "living"];

// the bare wayfarer: a knight out of the cold north — ASHEN. Skin the grey of a man three winters past
// sunlight, hair lank and black; the only warmth anywhere on him is the dried blood at his throat.
const SKIN  = ramp("#100e0d", "#33322f", "#4f4d48", "#6e6b64", "#8f8c82");
const WOOL  = ramp("#08080d", "#1a1b24", "#2b2d3a", "#3f4252", "#585c70"); // iron-dusk travel clothes
const SCARF = ramp("#160408", "#3c0d14", "#5c1620", "#7c222c", "#9e3440"); // dried-blood crimson
const HAIRC = ramp("#050404", "#141210", "#232019", "#353026", "#494435"); // black, unwashed
const AURA  = ramp("#07050c", "#120d1c", "#1d1530", "#2b2044", "#3d2f5c"); // the dark that walks with him
const RIM   = "#8fa8c8";   // Symphony's moon: one cold rim on the trailing edge, and nothing else pale

// affix treatments — each one a MOTION, not a colour swap; index 0 falsy on purpose
export const AFFIX_GLOW = [
  null,
  { name: "keen",     a: "#d8fbff", b: "#8ae9f6", mode: "shimmer" }, // razor shimmer running the edge
  { name: "heavy",    a: "#8a7358", b: "#4c3d2a", mode: "crack"   }, // the ground remembers each step
  { name: "warding",  a: "#7fc4ff", b: "#2a72c8", mode: "orbit"   }, // rune points circling the piece
  { name: "swift",    a: "#9ff7d0", b: "#3fc492", mode: "ghost"   }, // after-images trailing behind
  { name: "vampiric", a: "#ff5a5a", b: "#8e1020", mode: "thirst"  }, // red threads curling upward
  { name: "blazing",  a: "#ffd75a", b: "#ff7a1a", mode: "burn"    }, // fire teeth off the top edge
  { name: "hallowed", a: "#fff7d8", b: "#ffd88a", mode: "grace"   }, // a standing halo and slow motes
];

/** 0 → null (an empty slot draws the bare body); else the engine's tier/mat/affix unpack. */
export function unpackItem(v) {
  if (!v) return null;
  return unpackRaw(v);
}

// integer hash for seed-folded effects (blood): xorshift-ish, deterministic, dependency-free
function ihash(n) {
  let x = (n | 0) + 0x9e37;
  x = ((x ^ (x >> 7)) * 2654435761) >>> 0;
  x = (x ^ (x >> 13)) >>> 0;
  return x;
}

// blend two #rrggbb — used ONLY for whole-sprite state maps (hurt wash, corpse chill, char), never for
// shading; shading is authored in the ramps
function tint(a, b, t) {
  const A = parseInt(a.slice(1), 16), B = parseInt(b.slice(1), 16);
  const c = (sh) => {
    const v = Math.round(((A >> sh) & 255) * (1 - t) + ((B >> sh) & 255) * t);
    return (v < 16 ? "0" : "") + v.toString(16);
  };
  return "#" + c(16) + c(8) + c(0);
}
const CHILL = (c) => tint(c, "#232030", 0.5);    // dead things cool toward slate
const WOUND = (c) => tint(c, "#ff4646", 0.5);    // the hurt wash
const CHAR  = (c) => tint(c, "#120c0a", 0.7);    // burnt to the bone

// ── the stylus ───────────────────────────────────────────────────────────────────────────
// Carries origin, scale, mirror, cell clamp, colour map and an optional row BAND — the band selects a
// body zone (head / torso / legs) so a fatality can paint one part of the composed figure somewhere else.
// Every coordinate below is native cell pixels; the stylus is the only thing that touches the ctx.
function stylus(ctx, ox, oy, s, flip, cw, ch, map, band, lx = 0, ly = 0) {
  // lx/ly: extra LOW-side clamp, used when this cell is a part placed inside a larger box (fatalities
  // shift the warrior cell around the 96-box; without this a falling torso draws through the box floor)
  const put = (X, Y, w, h, col) => {
    if (X < lx) { w -= lx - X; X = lx; }
    if (Y < ly) { h -= ly - Y; Y = ly; }
    if (X + w > cw) w = cw - X;
    if (Y + h > ch) h = ch - Y;
    if (w <= 0 || h <= 0) return;
    ctx.fillStyle = map ? map(col) : col;
    ctx.fillRect(ox + X * s, oy + Y * s, w * s, h * s);
  };
  const g = {
    /** the one primitive: an integer rect, cell-local, authored facing-right */
    r(x, y, w, h, col) {
      if (!col) return;
      x |= 0; y |= 0; w |= 0; h |= 0;
      if (band) {
        if (y < band.y0) { h -= band.y0 - y; y = band.y0; }
        if (y + h > band.y1 + 1) h = band.y1 + 1 - y;
        if (h <= 0) return;
      }
      put(flip ? cw - x - w : x, y, w, h, col);
    },
    /** checkerboard — translucency, pixel-art dialect */
    d(x, y, w, h, col, ph = 0) {
      for (let j = 0; j < h; j++)
        for (let i = 0; i < w; i++)
          if (((x + i + y + j + ph) & 1) === 0) g.r(x + i, y + j, 1, 1, col);
    },
    /** stepped thick line — limbs, hafts, tails */
    seg(x0, y0, x1, y1, t, col) {
      const dx = x1 - x0, dy = y1 - y0, n = Math.max(Math.abs(dx), Math.abs(dy)) || 1;
      for (let i = 0; i <= n; i++)
        g.r(Math.round(x0 + dx * i / n), Math.round(y0 + dy * i / n), t, t, col);
    },
    /** outlined mass from row spans: spans[j] = [dx, w] | null. The outline is a dilation pass in the
     *  ramp's `o`, the fill a second pass in `m` — one continuous 1px rim, whatever the shape. Then the
     *  PAINTERLY pass: a dithered half-tone rolls the trailing quarter of every wide row into shadow and
     *  kisses the crown with light, so every mass in the game carries Symphony's soft tonal turn instead
     *  of a flat cel plane. Painters overpaint their own hard planes afterwards; the dither lives in the
     *  transitions between them, which is exactly where SotN keeps its paint. */
    rows(x0, y0, spans, P) {
      spans.forEach((sp, j) => { if (sp && sp[1] > 0) g.r(x0 + sp[0] - 1, y0 + j - 1, sp[1] + 2, 3, P.o); });
      spans.forEach((sp, j) => { if (sp && sp[1] > 0) g.r(x0 + sp[0], y0 + j, sp[1], 1, P.m); });
      const nrow = spans.length;
      spans.forEach((sp, j) => {
        if (!sp || sp[1] < 5) return;
        const [dx, w] = sp;
        for (let i = w - 1 - (w >> 2); i < w - 1; i++)
          if (((x0 + dx + i + y0 + j) & 1) === 0) g.r(x0 + dx + i, y0 + j, 1, 1, P.d);
        if (j < (nrow >> 2) && ((x0 + dx + y0 + j) & 1) === 0) g.r(x0 + dx + 1, y0 + j, 1, 1, P.l);
      });
    },
    /** outlined thick limb with a lit top-left ridge */
    tube(x0, y0, x1, y1, t, P) {
      g.seg(x0 - 1, y0 - 1, x1 - 1, y1 - 1, t + 2, P.o);
      g.seg(x0, y0, x1, y1, t, P.m);
      g.seg(x0, y0, x1, y1, 1, P.l);
    },
    /** tapering spike — horns, claws, blades of grass, icicles. dir in eighth-turns via (dx,dy). */
    taper(x, y, dx, dy, n, w0, P, litTip = true) {
      for (let i = 0; i < n; i++) {
        const w = Math.max(1, Math.round(w0 * (n - i) / n));
        const xx = dx < 0 ? x + dx * i - (w - 1) : x + dx * i;
        g.r(xx - 1, y + dy * i, w + 2, 1, P.o);
        g.r(xx, y + dy * i, w, 1, litTip && i >= n - 2 ? P.l : P.m);
      }
    },
    /** an eye with nothing behind it: socket, a hot iris, and a SLIT pupil that drifts with the idle —
     *  the drift is the "awake" tell. No white catchlight anywhere: a sparkle in the eye is a toy's. */
    orb(x, y, w, h, iris, sock, f = 0) {
      g.r(x - 1, y - 1, w + 2, h + 2, sock);
      g.r(x, y, w, h, iris);
      if (w >= 3) {
        const px2 = x + Math.min(w - 1, Math.max(0, (w >> 1) + [0, 1, -1][f % 3]));
        g.r(px2, y, 1, h, sock);
      }
    },
  };
  return g;
}

// ══ THE WAYFARER ═════════════════════════════════════════════════════════════════════════
// The figure is new from the boots up: ~3 head-heights, long-legged, a traveller more than a tank — the
// SILHOUETTE is still the build (six slots compose him), but the reads moved: tier now grows EDGES
// (pauldron points, crown horns, blade length) rather than sheer bulk, and the one constant across every
// kit is the red scarf, so "that is my guy" survives any gear roll.
//
// ADULT PROPORTIONS — the chibi DNA is dead. A ~54px figure at nearly six head-heights: a small skull
// over broad shoulders, a narrow waist, and LONG legs. The silhouette language is Blasphemous, not
// Saturday morning: gaunt, vertical, heavy at the shoulder and light at the hip.
// Skeleton bands (cell rows) — fatalities cut on these, so they are named once:
const HEAD_BAND  = { y0: 0,  y1: 17 };
const TORSO_BAND = { y0: 18, y1: 37 };
const LEGS_BAND  = { y0: 38, y1: 63 };
const HEAD_X = 27, HEAD_Y = 7;      // bare skull box 9×10, crown row 7
const TORSO_X = 23, TORSO_Y = 18;   // chest box 15 wide at the shoulder
const HIP_F = 31, HIP_B = 28, HIP_Y = 38;
const KNEE_Y = 47, ANKLE_Y = 56;    // soles end on 59, shadow on W_GROUND (60)

// Poses — hand-authored freeze-frames, facing right.
//   sink: whole-figure drop  ·  lean: torso/head push  ·  hx/hy: extra head snap
//   fk/ff bk/bf: knee/foot dx for front/back leg  ·  wp/sp: weapon/shield hand  ·  dir: blade eighth-dir
const W_POSES = {
  // leg offsets kept TIGHT: the first draft splayed feet ±9 and the row-lerp legs read as broken sticks —
  // a walker plants under his own weight, and the two-segment limbs below need honest knee angles
  walk: [
    { sink: 1, lean: 1,  fk: 2,  ff: 6,  bk: -2, bf: -5, wp: [42, 36], sp: [20, 33], dir: [0, -1], sw: 0 }, // reach
    { sink: 2, lean: 1,  fk: 2,  ff: 3,  bk: -1, bf: -2, wp: [43, 37], sp: [19, 34], dir: [0, -1], sw: 1 }, // plant
    { sink: 0, lean: 0,  fk: 0,  ff: 0,  bk: 0,  bf: 1,  wp: [41, 36], sp: [21, 33], dir: [0, -1], sw: 2 }, // cross
    { sink: 1, lean: 1,  fk: -1, ff: -4, bk: 2,  bf: 5,  wp: [40, 37], sp: [22, 34], dir: [0, -1], sw: 3 }, // drive
  ],
  attack: [
    { sink: 0, lean: -3, fk: 1,  ff: 4,  bk: -3, bf: -7, wp: [32, 6],  sp: [21, 32], dir: [-1, -1], sw: 1 }, // raise
    { sink: 2, lean: 5,  fk: 5,  ff: 10, bk: -3, bf: -6, wp: [47, 27], sp: [25, 34], dir: [1, 1], arc: 1, sw: 3 }, // cleave
    { sink: 2, lean: 3,  fk: 4,  ff: 7,  bk: -2, bf: -5, wp: [46, 39], sp: [24, 34], dir: [1, 0], sw: 2 }, // carry
  ],
  hit: { sink: 1, lean: -4, hx: -3, hy: -2, fk: 2, ff: 6, bk: -3, bf: -5, wp: [37, 30], sp: [17, 27], dir: [-1, 0], sw: 0 },
};
const TRAIL = [0, 1, 2, 1];          // cloak / scarf / plume trail per walk frame

// shared attachment points so a helm and a skull can never disagree
function joints(ps) {
  const tx = TORSO_X + ps.lean, ty = TORSO_Y + ps.sink;
  return {
    tx, ty,
    hx: HEAD_X + ps.lean + (ps.hx || 0), hy: HEAD_Y + ps.sink + (ps.hy || 0),
    shF: [tx + 10, ty + 2], shB: [tx + 4, ty + 3],
    hipF: HIP_F + (ps.lean >> 1), hipB: HIP_B + (ps.lean >> 1), hipY: HIP_Y + ps.sink,
  };
}

const dim = (P) => ({ o: P.o, d: P.o, m: P.d, l: P.m, s: P.l });   // far-side: one step into shadow

// ── affix motion ─────────────────────────────────────────────────────────────────────────
// Applied by each layer to its OWN item box {x,y,w,h}; `ph` de-phases the pieces of a matched set.
function affixFx(g, affix, box, f, ph = 0, live = true) {
  const A = AFFIX_GLOW[affix | 0];
  if (!A || !live) return;
  const { x, y, w, h } = box, k = (f + ph) & 3;
  switch (A.mode) {
    case "shimmer": {  // one glint SLIDING along the top edge — light catching metal. The old version
      // flashed a full border edge per beat, which read as a rotating frame around the gear, not a shine.
      const px = x + ((k * 3 + 1) % Math.max(1, w - 1));
      g.r(px, y - 1, 2, 1, A.a);
      g.r(px + 1, y - 1, 1, 1, "#ffffff");
      break;
    }
    case "crack": {    // stress marks stamped into the ground under the piece
      const gy = W_GROUND - 1;
      g.r(x + 1, gy, 3, 1, A.b);
      g.r(x + w - 3, gy - (k & 1), 3, 1, A.b);
      g.r(x + (w >> 1), gy - 1, 1, 1, A.a);
      break;
    }
    case "orbit": {    // four rune points circling the box
      const px = [x + (w >> 1), x + w + 2, x + (w >> 1), x - 3][k];
      const py = [y - 3, y + (h >> 1), y + h + 2, y + (h >> 1)][k];
      g.r(px, py, 2, 2, A.b);
      g.r(px, py, 1, 1, A.a);
      break;
    }
    case "ghost": {    // two after-images trailing off the back edge
      g.d(x - 4 - k, y + 1, 2, h - 2, A.a, k);
      g.d(x - 8 - k, y + 2, 2, h - 4, A.b, k + 1);
      break;
    }
    case "thirst": {   // red threads curling UP off the piece — hunger rising, not blood falling
      for (const [tx2, pp] of [[x + 1, 0], [x + w - 2, 2]]) {
        const rise = ((k + pp) & 3) * 2;
        g.r(tx2 + ((k & 1) ? 1 : 0), y - 3 - rise, 1, 3, A.a);
        g.r(tx2, y - 1 - rise, 1, 1, A.b);
      }
      break;
    }
    case "burn": {     // fire teeth off the top edge, heights from a fixed table
      const T = [2, 4, 1, 3, 2, 5, 3, 1];
      for (let i = 0; i < w; i += 2) {
        const t = T[((i >> 1) + k * 3) % T.length];
        g.r(x + i, y - t, 1, t, A.b);
        g.r(x + i, y - t, 1, 1, A.a);
      }
      break;
    }
    case "grace": {    // a standing halo arc and one slow mote
      const rw = Math.min(14, w + 6), rx = x + ((w - rw) >> 1);
      for (let i = 0; i < rw; i += 2) g.r(rx + i + (k & 1), y - 6, 1, 1, A.b);
      g.r(rx + (rw >> 1), y - 9 - k, 1, 1, A.a);
      break;
    }
  }
}

// ── layers, back to front ────────────────────────────────────────────────────────────────
// Every layer: (g, it, f, ps, J) — it = unpacked item or null (null draws the bare body part).

function wCloak(g, it, f, ps, J) {
  if (!it) { // bare back: the scarf's tail is the only thing that flies
    const s = TRAIL[ps.sw];
    g.rows(J.tx - 3 - s, J.ty + 1, [[0, 5], [-1, 6], [-2, 6], [-3, 5], [-3, 3]], SCARF);
    g.r(J.tx - 3 - s, J.ty + 2, 2, 2, SCARF.l);
    return;
  }
  const M = MATERIALS[it.mat], t = it.tier;
  const len = 22 + t * 2, s = TRAIL[ps.sw];      // long — the sweep of it is half the silhouette now
  const top = J.ty - 1;
  const spans = [];
  for (let i = 0; i < len; i++) {
    const u = i / (len - 1);
    const back = Math.round(u * (6 + t)) + (i > len - 6 ? s : 0);       // flares behind as it falls
    let w = 6 + Math.round(u * (3 + (t >> 1))) + (i > len - 6 ? s : 0);
    if (t >= 5 && (i === len - 1 || i === len - 3)) w -= 2;             // storm-worn hem
    spans.push([-back, w]);
  }
  g.rows(J.tx - 1, top, spans, M);
  for (let i = 2; i < len; i += 1) {                                    // one big lit plane, one shadow
    const [dx, w] = spans[i];
    if (i < len * 0.55) g.r(J.tx - 1 + dx, top + i, 2, 1, M.l);
    g.r(J.tx - 1 + dx + w - 2, top + i, 2, 1, M.d);
    if (i > 2 && (i & 1)) g.r(J.tx - 2 + dx, top + i, 1, 1, RIM);       // the MOONLIGHT RIM down the
  }                                                                     // trailing edge — Symphony's edge
  const [hdx, hw] = spans[len - 1];
  g.r(J.tx - 1 + hdx, top + len - 1, hw, 1, M.d);
  if (t >= 2) {                                                          // shoulder mantle
    g.r(J.tx - 3, top, 11, 2, M.o);
    g.r(J.tx - 2, top + 1, 9, 1, M.l);
  }
  if (t >= 4) g.r(J.tx - 1 + spans[len >> 1][0] + 2, top + 5, 1, len - 9, M.d);  // travel crease
  if (t >= 6) g.r(J.tx + 7, top + 1, 2, 2, M.s);                         // clasp — one glint, no white
  affixFx(g, it.affix, { x: J.tx - 6 - t, y: top, w: 12 + t, h: len }, f, 5, g.fx);
}

function wLeg(g, hipX, hipY, kdx, fdx, sink, torso, boot, bootTop, P, B) {
  // TWO SOLID SEGMENTS with a real knee — thigh 6 thick, shin 5 — drawn as outlined tubes, not a
  // row-lerped stair of 1px steps (the first draft's "crooked legs", killed with prejudice). The boot
  // ramp takes over the shin from bootTop down, so armoured greaves still climb with tier.
  const ay = ANKLE_Y + sink;
  const kx = hipX + kdx, ky = KNEE_Y + sink - 1;
  const ax = hipX + fdx;
  g.tube(hipX, hipY, kx, ky, 5, P);                       // the thigh — LONG and lean now, not a stump
  g.r(kx, ky - 1, 5, 2, P.d);                             // knee crease seats the joint
  const shinC = boot && bootTop <= ky + 2 ? B : P;
  g.tube(kx + 1, ky + 1, ax + 1, ay - 1, 4, shinC);       // the shin
  if (boot && bootTop > ky + 2 && bootTop < ay) {         // low boot: cuff partway up the shin
    g.tube(kx + 1 + Math.round((ax - kx) * (bootTop - ky) / Math.max(1, ay - ky)), bootTop, ax + 1, ay - 1, 4, B);
  }
  const C = boot ? B : P;
  g.r(ax - 2, ay, 9, 4, C.o);                             // the boot block; outline bottom row is the sole
  g.r(ax - 1, ay, 7, 3, C.m);
  g.r(ax - 1, ay, 3, 1, C.l);
  g.r(ax + 4, ay + 1, 2, 1, C.l);                         // toe light
  g.r(ax - 1, ay + 2, 2, 1, C.d);                         // heel
  return ax;
}

function wBoots(g, it, f, ps, J) {
  const M = it ? MATERIALS[it.mat] : null, t = it ? it.tier : -1;
  const bootTop = it ? Math.max(J.hipY + 2, ANKLE_Y - 3 - t) : ANKLE_Y;
  wLeg(g, J.hipB, J.hipY, ps.bk, ps.bf, ps.sink, WOOL, true, bootTop, dim(WOOL), M ? dim(M) : dim(WOOL));
  const ax = wLeg(g, J.hipF, J.hipY, ps.fk, ps.ff, ps.sink, WOOL, true, bootTop, WOOL, M || WOOL);
  if (M && t >= 3) {                             // poleyn: the knee stops being cloth
    const kx = J.hipF + ps.fk;
    g.r(kx - 1, KNEE_Y - 2, 6, 4, M.o);
    g.r(kx, KNEE_Y - 1, 4, 2, M.m);
    g.r(kx, KNEE_Y - 1, 4, 1, M.l);
  }
  if (M && t >= 1) g.r(ax - 1, bootTop, 6, 1, M.l);          // cuff
  if (M && t >= 5) g.taper(ax + 6, ANKLE_Y + ps.sink + 1, 1, 0, 3, 2, M);  // sabaton point
  if (M && t >= 7) g.taper(ax - 2, ANKLE_Y + ps.sink, -1, -1, 4, 2, M);    // heel spur
  if (M) affixFx(g, it.affix, { x: J.hipB - 1, y: bootTop, w: 14, h: ANKLE_Y - bootTop + 4 }, f, 3, g.fx);
}

function wBody(g, it, f, ps, J) {
  const M = it ? MATERIALS[it.mat] : WOOL, t = it ? it.tier : -1;
  const x = J.tx, y = J.ty;
  // a MAN'S torso: 15 at the shoulder, 9 at the waist, 20 rows tall — the V of someone who has carried
  // a blade for years, drawn over the legs so skirts and tassets can fall
  g.rows(x + 2, y, [
    [0, 11], [0, 11], [0, 11], [0, 11], [0, 10],
    [1, 9], [1, 9], [2, 8], [2, 7], [2, 7],
    [2, 7], [2, 7], [2, 7], [2, 8], [1, 9],
    [1, 9], [1, 9], [1, 10], [2, 9], [2, 8],
  ], M);
  g.r(x + 3, y + 1, 3, 6, M.l);                  // lit chest plane (what light there is, upper-left)
  g.r(x + 10, y + 1, 2, 9, M.d);                 // the chest curve rolling into shadow
  g.r(x + 4, y + 8, 6, 1, M.d);                  // under-chest shadow
  g.r(x + 6, y - 1, 3, 1, SKIN.m);               // the neck, one hard sliver
  // THE SCARF — the one blood-note he owns, at the throat, every kit
  g.r(x + 4, y, 7, 2, SCARF.o);
  g.r(x + 5, y, 5, 1, SCARF.m);
  g.r(x + 9, y + 1, 2, 3, SCARF.d);              // the knot, at the throat's lee side
  if (!it) {                                     // bare: a belted travel tunic, no ornament
    g.r(x + 4, y + 5, 1, 7, WOOL.d);
    g.r(x + 9, y + 5, 1, 7, WOOL.d);
    g.r(x + 3, y + 12, 9, 2, WOOL.o);
    g.r(x + 4, y + 12, 7, 1, WOOL.l);
    affixFx(g, 0, { x, y, w: 13, h: 18 }, f, 1, g.fx);
    return;
  }
  if (t >= 1) {                                  // war-belt + square buckle, slung at the hip
    g.r(x + 3, y + 14, 9, 2, M.d);
    g.r(x + 6, y + 13, 3, 4, M.o);
    g.r(x + 7, y + 14, 1, 2, M.s);
  }
  if (t >= 2) {                                  // cuirass ridge down the sternum
    g.r(x + 7, y + 1, 1, 10, M.l);
    g.r(x + 8, y + 2, 1, 9, M.d);
  }
  if (t >= 3) {                                  // pauldron POINTS — tier grows edges, never bulk
    const pw = Math.min(7, 3 + (t >> 1));
    g.rows(J.shF[0] - 1, J.shF[1] - 3, [[1, pw - 1], [0, pw + 1], [0, pw + 1], [1, pw - 1]], M);
    g.r(J.shF[0], J.shF[1] - 2, pw - 1, 1, M.l);
    g.taper(J.shF[0] + pw, J.shF[1] - 2, 1, -1, Math.min(4, t - 1), 2, M);
    g.rows(J.shB[0] - 2, J.shB[1] - 2, [[1, pw - 2], [0, pw], [1, pw - 2]], dim(M));
  }
  if (t >= 4) {                                  // faulds skirting the hips
    g.r(x + 3, y + 16, 9, 2, M.o);
    g.r(x + 4, y + 16, 7, 1, M.m);
    g.r(x + 4, y + 18, 7, 2, M.d);
    g.r(x + 7, y + 16, 1, 3, M.o);
  }
  if (t >= 6) {                                  // the star-stone at the sternum — the ONE jewel
    g.r(x + 6, y + 5, 3, 3, M.o);
    g.r(x + 7, y + 5, 1, 3, M.s);
  }
  affixFx(g, it.affix, { x: x + 2, y, w: 11, h: 18 }, f, 1, g.fx);
}

function wHead(g, it, f, ps, J) {
  const x = J.hx, y = J.hy;
  // a REAL skull: 9 wide, 10 tall, one-sixth of the man — the single strongest adult-proportion signal
  g.rows(x, y, [
    [2, 6], [1, 8], [0, 9], [0, 9], [0, 10], [0, 10], [0, 8], [1, 7], [2, 5], [3, 3],
  ], SKIN);                                       // rows 4-5: the NOSE breaks the front edge — profile
  g.r(x + 1, y + 2, 2, 4, SKIN.l);               // back-crown light
  const M = it ? MATERIALS[it.mat] : null, t = it ? it.tier : -1;
  if (!it || t < 2) {                            // the FACE in profile — planes of dark, one glint
    g.r(x + 4, y + 2, 5, 1, SKIN.o);             // the brow's shadow band
    g.r(x + 6, y + 3, 2, 1, SKIN.d);             // the sunken socket
    g.r(x + 7, y + 3, 1, 1, "#b8b2a4");          // the glint, fixed down the road
    g.r(x + 9, y + 5, 1, 1, SKIN.d);             // the nostril under the nose's break
    g.r(x + 6, y + 7, 3, 1, SKIN.o);             // the mouth, a hard line drawn back
    g.r(x + 5, y + 5, 1, 2, SKIN.o);             // gaunt cheek hollow
  }
  if (!it) {                                     // bare: lank black hair down the back of the skull
    g.rows(x - 2, y - 2, [
      [3, 6], [1, 9], [0, 10], [0, 5], [0, 4], [0, 4], [0, 3], [0, 3], [0, 3], [1, 2],
    ], HAIRC);
    g.r(x, y - 1, 3, 1, HAIRC.l);                // one cold sheen along the crown
    g.r(x + 5, y, 3, 1, HAIRC.m);                // the fringe cutting the brow
    g.d(x + 5, y + 8, 3, 1, SKIN.d, 0);          // stubble on the gaunt jaw
    const s = TRAIL[ps.sw];
    g.r(x - 3 - (s >> 1), y + 3, 1, 4, HAIRC.d); // a loose strand drifting with the walk
    affixFx(g, 0, { x, y, w: 9, h: 10 }, f, 2, g.fx);
    return;
  }
  if (t < 2) {                                   // t0-1: an open war-hood / kettle rim
    g.rows(x - 1, y - 2, [[3, 6], [1, 9], [0, 11], [0, 11], [-1, 13], [0, 3]], M);
    g.r(x, y - 1, 4, 1, M.l);
    g.r(x - 2, y + 2, 13, 1, M.o);               // the brim line
    if (t >= 1) { g.r(x + 7, y + 2, 2, 4, M.m); g.r(x + 7, y + 2, 1, 4, M.l); }  // nasal bar
  } else {                                       // t2+: the closed helm — a burning slit for a face
    g.rows(x - 1, y - 2, [
      [3, 6], [1, 9], [0, 11], [0, 11], [0, 11], [0, 11], [0, 11], [0, 11],
      [1, 10], [1, 9], [2, 7], [3, 5],
    ], M);
    g.r(x, y - 1, 4, 2, M.l);
    g.r(x - 1, y + 1, 1, 5, RIM);                // moonlight on the trailing cheek
    g.r(x + 7, y, 3, 7, M.d);
    g.r(x - 1, y + 2, 11, 1, M.d);               // brow seam
    g.r(x + 3, y + 3, 7, 2, M.o);                // the visor slot…
    g.r(x + 4, y + 4, 5, 1, "#ffb84a");          // …and the ember behind it
    g.r(x + 4, y + 4, 1, 1, "#fff1c8");
    if (t >= 3) for (let k2 = 0; k2 < 2; k2++) g.r(x + 5 + k2 * 2, y + 7, 1, 1, M.o); // breaths
  }
  if (t >= 4) {                                  // crest fin sweeping backward
    g.rows(x, y - 5, [[4, 3], [2, 6], [0, 8]], M);
    g.r(x + 2, y - 4, 3, 1, M.l);
  }
  if (t >= 5) {                                  // crown horns — small, honed, mean
    g.taper(x - 1, y - 2, -1, -1, 4, 2, M);
    g.taper(x + 9, y - 2, 1, -1, 4, 2, M);
  }
  if (t >= 6) {                                  // the plume, streaming with the walk
    const s = TRAIL[ps.sw];
    g.rows(x - 3 - s, y - 6, [[3, 3], [1, 5], [-1, 6], [-3, 6], [-5, 5]], SCARF);
    g.r(x - 1 - s, y - 5, 3, 1, SCARF.l);
  }
  if (t >= 7) g.r(x + 4, y - 4, 1, 1, M.s);      // the crown star — one point of light, no white
  affixFx(g, it.affix, { x, y: y - (t >= 5 ? 4 : 0), w: 9, h: 10 }, f, 2, g.fx);
}

function wShield(g, it, f, ps, J) {
  const M = it ? MATERIALS[it.mat] : null, t = it ? it.tier : -1;
  if (!M) return;                                // bare back: nothing slung, the cloak owns it
  // slung across the BACK, tilted with the stride — a knight in profile carries it, he does not hold
  // it at arm's length like a waiter with a tray (which is what the frontal draft looked like)
  const w = 8 + t, h = 10 + t * 2;
  const s = TRAIL[ps.sw];
  const sx = J.tx - 6 - (t >> 1), sy = J.ty + 1 + (s >> 1);
  const spans = [];
  for (let j = 0; j < h; j++) {
    const rr = Math.min(j, h - 1 - j);
    const ins = rr === 0 ? 2 : rr === 1 ? 1 : 0;
    const pt = t >= 3 && j === h - 1 ? 1 : 0;    // kite point grows from t3
    const tilt = -(j >> 2);                      // the slung tilt: top leans out over the cloak
    spans.push([ins + pt + tilt, w - (ins + pt) * 2]);
  }
  g.rows(sx, sy, spans, M);
  g.r(sx + 1, sy + 1, w - 4, 2, M.l);
  g.r(sx - (h >> 3), sy + 2, 2, h - 6, RIM);     // the moon catches the slung edge
  g.r(sx + w - 4, sy + 3, 2, h - 6, M.d);
  if (t >= 1) {                                  // the DEVICE: a scarf-red CHEVRON — his heraldry
    const cy = sy + (h >> 1) - 2;
    for (let i = 0; i < (w >> 1) - 1; i++) {
      g.r(sx + i - 1, cy + i, 2, 2, SCARF.m);
      g.r(sx + w - 4 - i, cy + i, 2, 2, SCARF.m);
    }
  }
  if (t >= 4) for (let j = 3; j < h - 3; j += 3) g.r(sx + w - 2 - (j >> 2), sy + j, 1, 1, M.s);  // rim studs
  if (t >= 6) g.taper(sx + 1 - (h >> 3), sy - 1, 0, -1, 4, 2, M);                     // crown spike
  affixFx(g, it.affix, { x: sx - 2, y: sy, w, h }, f, 4, g.fx);
}

/** The weapon's class — a REAL item property the contract rolls and the combat math uses (see the engine's
 *  weaponKind + fight), not a look derived here. The art just draws the iron the chain already decided. */
const W_KIND = (it) => it.kind | 0;   // 0 sword · 1 axe · 2 maul · 3 spear

/** Affix glow laid ALONG the weapon — walked cell by cell down the actual metal, never a bounding box.
 *  The box version put burn teeth and orbit runes on the CORNERS of the blade's bbox, which for a raised
 *  or diagonal blade is empty air: glow floating NEXT TO the sword, the exact recurring complaint.
 *  (qx,qy) is the blade's own perpendicular; drift that must read as "rising" uses world-up. */
function weaponFx(g, affix, bx, by, dx, dy, reach, f, live) {
  const A = AFFIX_GLOW[affix | 0];
  if (!A || !live) return;
  const qx = -dy, qy = dx, k = f & 3;
  const cx = (i) => bx + dx * i, cy = (i) => by + dy * i;
  switch (A.mode) {
    case "shimmer": {  // one glint travelling up the metal
      const i = 3 + ((k * 3 + 1) % Math.max(1, reach - 3));
      g.r(cx(i) + qx, cy(i) + qy, 1, 1, "#ffffff");
      g.r(cx(i + 1) + qx, cy(i + 1) + qy, 1, 1, A.a);
      break;
    }
    case "crack": {    // sparks grinding off the tip
      g.r(cx(reach) + dx + ((k & 1) ? qx : -qx), cy(reach) + dy + ((k & 1) ? qy : -qy), 1, 1, A.a);
      g.r(cx(reach - 1) - qx, cy(reach - 1) - qy, 1, 1, A.b);
      break;
    }
    case "orbit": {    // two runes sliding along the metal, opposite faces
      const span = Math.max(1, reach - 3);
      const i1 = 3 + ((k * 4) % span), i2 = 3 + ((k * 4 + (span >> 1)) % span);
      g.r(cx(i1) + qx * 2, cy(i1) + qy * 2, 2, 2, A.b);
      g.r(cx(i1) + qx * 2, cy(i1) + qy * 2, 1, 1, A.a);
      g.r(cx(i2) - qx * 2, cy(i2) - qy * 2, 2, 2, A.b);
      break;
    }
    case "ghost": {    // an after-image of the metal itself, one step behind the trailing face
      for (let i = 3; i <= reach; i += 2) g.r(cx(i) - qx * 2, cy(i) - qy * 2, 1, 1, A.a);
      for (let i = 4; i <= reach; i += 3) g.r(cx(i) - qx * 4, cy(i) - qy * 4, 1, 1, A.b);
      break;
    }
    case "thirst": {   // red threads curling up off the metal
      for (const [i, pp] of [[4, 0], [Math.max(5, reach - 2), 2]]) {
        const rise = ((k + pp) & 3) * 2;
        g.r(cx(i), cy(i) - 3 - rise, 1, 3, A.a);
        g.r(cx(i), cy(i) - 1 - rise, 1, 1, A.b);
      }
      break;
    }
    case "burn": {     // fire teeth off the edge cells, rising in world space
      const T = [2, 4, 1, 3, 2, 5, 3, 1];
      for (let i = 3; i <= reach; i += 2) {
        const h = T[((i >> 1) + k * 3) % T.length];
        g.r(cx(i) + qx, cy(i) + qy - h, 1, h, A.b);
        g.r(cx(i) + qx, cy(i) + qy - h, 1, 1, A.a);
      }
      break;
    }
    case "grace": {    // motes strung along the metal + one drifting off the tip
      for (let i = 4; i <= reach; i += 3) {
        const s = (i + k) & 1 ? 1 : -1;
        g.r(cx(i) + qx * s, cy(i) + qy * s, 1, 1, A.b);
      }
      g.r(cx(reach), cy(reach) - 2 - k, 1, 1, A.a);
      break;
    }
  }
}

function wWeapon(g, it, f, ps, J) {
  const M = it ? MATERIALS[it.mat] : null, t = it ? it.tier : -1;
  const [hx2, hy2] = ps.wp;
  g.tube(J.shF[0], J.shF[1], hx2, hy2, 3, SKIN); // the near arm is his — gauntlets read on the blade hand
  g.r(hx2 - 1, hy2 - 1, 5, 5, M && t >= 2 ? M.o : SKIN.o);
  g.r(hx2, hy2, 3, 3, M && t >= 2 ? M.m : SKIN.m);
  g.r(hx2, hy2, 1, 1, M && t >= 2 ? M.l : SKIN.l);
  if (!M) {                                      // bare hands: a walking stick
    g.seg(hx2 + 1, hy2 - 8, hx2 + 1, hy2 + 10, 2, HAIRC.d);
    g.r(hx2, hy2 - 8, 3, 2, HAIRC.m);
    return;
  }
  const [dx, dy] = ps.dir;
  const qx = -dy, qy = dx;                       // the weapon's own perpendicular
  const kind = W_KIND(it);
  const bx = hx2 + 1, by = hy2 + 1;
  let reach;                                     // how far the metal actually extends — wake + glow use THIS
  if (kind === 1) {                              // ── AXE: wooden haft, bearded bit, double-bit at t5+
    reach = 13 + t;
    g.seg(bx, by, bx + dx * reach, by + dy * reach, 2, HAIRC.d);
    g.r(bx + dx * 2, by + dy * 2, 1, 1, M.d);    // grip wrap
    g.r(bx + dx * 4, by + dy * 4, 1, 1, M.d);
    const hh = reach - 3;                        // where the head sits on the haft
    const BIT = [3, 5, 6, 6, 5, 3];              // convex cutting face, bearded top and bottom
    // per-pixel walks along the perpendicular: the pose axis can be diagonal, so a rect span can't
    // carry the head shape (and g.r silently drops negative extents)
    for (let j = 0; j < BIT.length; j++) {
      const ax = bx + dx * (hh - 2 + j), ay = by + dy * (hh - 2 + j);
      for (let w = 1; w <= BIT[j]; w++)
        g.r(ax + qx * w, ay + qy * w, 1, 1, w === BIT[j] ? (j >= 2 && j <= 3 ? M.s : M.l)   // the true edge
          : w === 1 || BIT[j] <= 3 ? M.o : M.m);
      if (t >= 5) {                              // double-bit: a smaller mirror on the back face
        const b2 = BIT[j] - 2;
        for (let w = 1; w <= b2; w++)
          g.r(ax - qx * w, ay - qy * w, 1, 1, w === b2 ? M.l : M.o);
      }
    }
    if (t >= 3) g.taper(bx + dx * (reach + 1), by + dy * (reach + 1), dx, dy, 3, 1, M);   // top spike
  } else if (kind === 2) {                       // ── MAUL: short haft, a head that ENDS arguments
    reach = 12 + t;
    g.seg(bx, by, bx + dx * reach, by + dy * reach, 2, HAIRC.d);
    g.r(bx + dx * 3, by + dy * 3, 1, 1, M.d);    // ferrule band
    const tx2 = bx + dx * reach, ty2 = by + dy * reach;
    g.r(tx2 - 3, ty2 - 3, 7, 6, M.o);            // the block
    g.r(tx2 - 2, ty2 - 2, 5, 4, M.m);
    g.r(tx2 - 2 + (qx > 0 ? 3 : 0), ty2 - 2 + (qy > 0 ? 2 : 0), 2, 2, M.l);   // striking face catches light
    if (t >= 2) { g.r(tx2 - 3, ty2 - 3, 1, 1, M.s); g.r(tx2 + 3, ty2 + 2, 1, 1, M.s); }  // studs
    if (t >= 5) {                                // flanges: spikes off every face
      g.taper(tx2 + dx * 3, ty2 + dy * 3, dx, dy, 3, 1, M);
      g.taper(tx2 + qx * 4, ty2 + qy * 4, qx, qy, 2, 1, M);
      g.taper(tx2 - qx * 4, ty2 - qy * 4, -qx, -qy, 2, 1, M);
    }
    reach += 2;                                  // the head extends past the haft
  } else if (kind === 3) {                       // ── SPEAR: the longest reach, a leaf point, tassel at t6+
    reach = 16 + t * 2;
    g.seg(bx - dx * 3, by - dy * 3, bx + dx * reach, by + dy * reach, 1, HAIRC.m);   // full haft, both ways
    g.r(bx + dx * 2, by + dy * 2, 1, 1, M.d);    // binding wraps
    g.r(bx + dx * 5, by + dy * 5, 1, 1, M.d);
    g.taper(bx + dx * reach, by + dy * reach, dx, dy, 6, 2, M);                       // the leaf head
    g.r(bx + dx * (reach + 5), by + dy * (reach + 5), 1, 1, M.s);                     // its bright point
    if (t >= 4) { g.r(bx + dx * (reach - 1) + qx * 2, by + dy * (reach - 1) + qy * 2, 1, 1, M.o);   // lugs
      g.r(bx + dx * (reach - 1) - qx * 2, by + dy * (reach - 1) - qy * 2, 1, 1, M.o); }
    if (t >= 6) { g.r(bx + dx * (reach - 2), by + dy * (reach - 2) + 1, 1, 3, SCARF.m);           // tassel
      g.r(bx + dx * (reach - 2), by + dy * (reach - 2) + 4, 1, 1, SCARF.d); }
    reach += 5;                                  // the point extends past the haft
  } else {                                       // ── SWORD: crossguard, true edge, dark spine
    const len = 15 + t * 2;                      // t0 short sword … t7 greatblade
    reach = len;
    // crossguard, perpendicular to the blade
    g.r(bx - (dy !== 0 ? 3 : 1), by - (dx !== 0 ? 3 : 1), dy !== 0 ? 8 : 3, dx !== 0 ? 8 : 3, M.o);
    g.r(bx - (dy !== 0 ? 2 : 0), by - (dx !== 0 ? 2 : 0), dy !== 0 ? 6 : 2, dx !== 0 ? 6 : 2, M.m);
    // the blade: a 3px core with a bright true edge and a dark spine
    for (let i = 2; i <= len; i++) {
      const X = bx + dx * i, Y = by + dy * i;
      g.r(X - 1, Y - 1, 3, 3, M.o);
    }
    for (let i = 2; i <= len; i++) {
      const X = bx + dx * i, Y = by + dy * i;
      g.r(X, Y, 1, 1, i > len - 3 ? M.s : M.m);
      if (t >= 2) g.r(X + (dy !== 0 ? 1 : 0), Y + (dx !== 0 ? 1 : 0), 1, 1, M.l);   // the edge
      if (t >= 4) g.r(X - (dy !== 0 ? 1 : 0), Y - (dx !== 0 ? 1 : 0), 1, 1, M.d);   // the spine
    }
    if (t >= 5) { g.r(bx - 1, by + 3, 1, 1, M.s); }                       // pommel gem
    if (t >= 7) g.taper(bx + dx * (len >> 1) + (dy !== 0 ? 2 : 0), by + dy * (len >> 1), dx, dy, 4, 2, M); // parry hook
  }
  const len = reach;                             // the wake below measures from the true tip, any kind
  if (ps.arc) {
    // The wake GLOWS OUT OF THE SWORD. The old trail was an arc at tip-radius plus an inner echo —
    // two thin concentric crescents that touched the blade at exactly one point and read as separate
    // effects stacked behind it. Now: radial streaks that each run ALONG a recent blade position,
    // hugging the metal at the freshest angle and shrinking/dimming as they trail back through the
    // swept angle — light peeling off the edge, attached to it for its whole length.
    const scx = J.shF[0], scy = J.shF[1];
    const tpX = bx + dx * len, tpY = by + dy * len;
    const R2 = Math.max(10, Math.round(Math.hypot(tpX - scx, tpY - scy)));
    const a1 = Math.atan2(tpY - scy, tpX - scx);      // where the edge IS, right now
    for (let i2 = 0; i2 < 6; i2++) {
      const aa = a1 - 0.16 - i2 * 0.24;               // just behind the edge, sweeping back
      const r1 = R2 * (1 - i2 * 0.06);                // the wake decays away from the tip…
      const r0 = R2 * (0.35 + i2 * 0.07);             // …and pulls off the hilt as it ages
      g.seg(Math.round(scx + Math.cos(aa) * r0), Math.round(scy + Math.sin(aa) * r0),
            Math.round(scx + Math.cos(aa) * r1), Math.round(scy + Math.sin(aa) * r1),
            i2 < 2 ? 2 : 1, i2 === 0 ? M.s : i2 < 3 ? M.l : M.m);
    }
    // and the edge itself BURNS: a bright sheath laid directly on the blade's leading side
    for (let i = 4; i <= len; i += 2)
      g.r(bx + dx * i + (dy !== 0 ? 2 : 0), by + dy * i + (dx !== 0 ? 2 : 0), 1, 1, M.s);
  }
  weaponFx(g, it.affix, bx, by, dx, dy, reach, f, g.fx);
}

// ── composing him ────────────────────────────────────────────────────────────────────────
const NO_GEAR = [0, 0, 0, 0, 0, 0];

/** THE DARK THAT WALKS WITH HIM — a standing shade behind the shoulders, wisps tearing loose, one ember
 *  of the old blood. Drawn FIRST so it hangs behind the figure; it is what the bright first draft lost. */
function wAura(g, J, f) {
  const k = f & 3;
  g.d(J.tx - 6, J.ty - 10 - k, 7, 15, AURA.m, k);
  g.d(J.tx - 10, J.ty - 3, 4, 11, AURA.d, k + 1);
  g.d(J.tx + 12, J.ty - 6, 3, 9, AURA.d, k);
  g.r(J.tx - 4 - k, J.ty - 13 - k * 2, 1, 3, AURA.l);     // a wisp tearing free
  g.r(J.tx + 11 + (k & 1), J.ty - 9 - k, 1, 2, AURA.l);
  g.r(J.tx - 1, J.ty - 15 - k * 2, 1, 1, SCARF.m);        // one ember of the old blood
}

function paintWayfarer(g, gear, ps, f) {
  const it = (i) => unpackItem(gear[i] | 0);
  const J = joints(ps);
  if (g.fx) wAura(g, J, f);
  wCloak(g, it(5), f, ps, J);
  wShield(g, it(3), f, ps, J);
  wBoots(g, it(4), f, ps, J);
  wBody(g, it(2), f, ps, J);
  wHead(g, it(1), f, ps, J);
  wWeapon(g, it(0), f, ps, J);
}

/** The warrior, felled — an AUTHORED sprawl, not a pose knocked sideways: face-up along the road, one
 *  arm flung, the blade fallen a stride away. Drawn in his gear's colours so the corpse is still HIS. */
function paintFallen(g, gear) {
  const it = (i) => unpackItem(gear[i] | 0);
  const bM = it(2) ? MATERIALS[it(2).mat] : WOOL;
  const hM = it(1) ? MATERIALS[it(1).mat] : null;
  const wM = it(0) ? MATERIALS[it(0).mat] : null;
  const gy = W_GROUND;
  // legs folded left, torso centre, head right — reading order is feet-first like a battlefield find
  g.rows(8, gy - 7, [[2, 12], [0, 16], [0, 16], [1, 14]], WOOL);            // folded legs
  g.r(10, gy - 6, 4, 1, WOOL.l);
  g.rows(22, gy - 9, [[2, 15], [0, 19], [0, 20], [0, 19], [1, 16]], bM);    // the chest, side-on
  g.r(24, gy - 8, 8, 2, bM.l);
  g.r(26, gy - 5, 12, 2, bM.d);
  g.r(30, gy - 10, 6, 2, SCARF.m);                                          // the scarf, spilled
  g.r(34, gy - 9, 8, 2, SCARF.d);
  const hx2 = 43;                                                           // the head, tipped back
  g.rows(hx2, gy - 8, [[2, 6], [0, 10], [0, 10], [0, 10], [1, 8], [3, 4]], hM || SKIN);
  if (hM) { g.r(hx2 + 2, gy - 7, 5, 1, hM.l); g.r(hx2 + 2, gy - 5, 6, 1, hM.o); }
  else {
    g.r(hx2 + 3, gy - 6, 4, 1, SKIN.d);                                     // shut eyes
    g.r(hx2 + 4, gy - 3, 3, 1, SKIN.o);
  }
  g.tube(26, gy - 8, 18, gy - 2, 3, dim(bM));                               // the flung arm
  g.r(16, gy - 3, 4, 3, SKIN.m);                                            // open hand
  if (wM) {                                                                 // the dropped weapon — HIS kind
    const wk = W_KIND(it(0));
    if (wk === 1) {                 // axe: haft + bearded bit standing proud of the ground
      g.seg(52, gy - 2, 61, gy - 2, 2, HAIRC.d);
      g.rows(59, gy - 7, [[1, 3], [0, 4], [0, 4], [1, 3]], wM);
      g.r(62, gy - 6, 1, 3, wM.l);
    } else if (wk === 2) {          // maul: haft + the block
      g.seg(52, gy - 2, 60, gy - 2, 2, HAIRC.d);
      g.r(59, gy - 5, 5, 4, wM.o);
      g.r(60, gy - 4, 3, 2, wM.m);
      g.r(60, gy - 4, 1, 1, wM.s);
    } else if (wk === 3) {          // spear: the long haft, point past the reading edge
      g.seg(48, gy - 2, 62, gy - 2, 1, HAIRC.m);
      g.taper(62, gy - 2, 1, 0, 4, 2, wM);
      g.r(55, gy - 2, 1, 1, wM.d);
    } else {                        // sword, as it always fell
      g.seg(52, gy - 2, 62, gy - 2, 2, wM.o);
      g.seg(53, gy - 2, 60, gy - 2, 1, wM.m);
      g.r(61, gy - 2, 1, 1, wM.s);
      g.r(52, gy - 4, 2, 5, wM.d);
    }
  }
}

/**
 * Draw one warrior frame with its TOP-LEFT corner at (x, y) — a 64×64 cell, feet on row 59, contact
 * shadow on row 60. opts = { gear[6 packed], frame, scale, facing (+1 right), hurt, dead, attacking }.
 * Same opts, same pixels — always.
 */
export function drawWarrior(ctx, x, y, opts = {}) {
  const gear = opts.gear || NO_GEAR;
  const f = Math.max(0, opts.frame | 0);
  const scale = Math.max(1, opts.scale | 0 || 1);
  const facing = opts.facing === -1 ? -1 : 1;
  const dead = !!opts.dead;
  const map = dead ? CHILL : opts.hurt && !opts.attacking ? WOUND : null;
  ctx.imageSmoothingEnabled = false;
  const g = stylus(ctx, x, y, scale, facing === -1, FRAME_W, FRAME_H, map, null);
  g.fx = !dead;                                   // corpses stop glowing
  for (let i = 0; i < 44; i += 2) g.r(10 + i, W_GROUND + ((i & 2) ? 1 : 0), 1, 1, "#191420");
  if (dead) paintFallen(g, gear);
  else {
    const ps = opts.attacking ? W_POSES.attack[f % 3]
      : opts.hurt ? W_POSES.hit
      : W_POSES.walk[f % 4];
    paintWayfarer(g, gear, ps, f);
  }
  return { w: FRAME_W * scale, h: FRAME_H * scale };
}

/** The full strip — 4 walk, 3 attack, hit, death — for baking or a gear-preview reel. */
export function drawWarriorSheet(ctx, x, y, opts = {}) {
  const scale = Math.max(1, opts.scale | 0 || 1);
  let cx2 = x;
  for (let f = 0; f < 4; f++) { drawWarrior(ctx, cx2, y, { ...opts, frame: f, scale }); cx2 += FRAME_W * scale; }
  for (let f = 0; f < 3; f++) { drawWarrior(ctx, cx2, y, { ...opts, frame: f, scale, attacking: true }); cx2 += FRAME_W * scale; }
  drawWarrior(ctx, cx2, y, { ...opts, frame: 0, scale, hurt: true }); cx2 += FRAME_W * scale;
  drawWarrior(ctx, cx2, y, { ...opts, frame: 0, scale, dead: true }); cx2 += FRAME_W * scale;
  return { w: cx2 - x, h: FRAME_H * scale, cells: 9 };
}

// ══ THE BESTIARY ═════════════════════════════════════════════════════════════════════════
// Thirty-six creatures: five realms × three contract families × two ranks, five realm BOSSES, and the
// MIMIC. The contract only knows (family, rank, level); WHICH creature wears those stats is the realm's
// business — the biome is rolled by the chain (autogame-engine.js/biomeFor) and handed in as opts.biome.
// Family still owns the tactical READ, in every realm alike:
//   family 0 · the SWARM — small, low, fast-looking. You will fight many.
//   family 1 · the WALL  — a mass with a weapon. The swing you price your aggression against.
//   family 2 · the SPARK — a caster. Thin, strange, and it reaches you at range on the strike frame.
// Rank changes the DRAWING (species!), never a scale factor; level warms the eyes and studs the spine.
//
// All monsters are authored FACING LEFT, into the oncoming wayfarer.

const FY = MFOOT;                        // feet end here
const heatOf = (lvl) => Math.min(3, ((lvl | 0) / 6) | 0);
const HEAT = ["#ffd23a", "#ff9e2e", "#ff5a24", "#ff2222"];  // eye temperature by depth

// shared poses — dy sinks the mass, lx lunges it (left = toward the hero), jaw opens the maw,
// br swells the chest, wind/hit/fall flag the special frames
const M_POSES = [
  { dy: 0,  lx: 0,  jaw: 0, br: 0 },            // 0 settle — most of the loop is spent HERE, dead still
  { dy: -1, lx: 0,  jaw: 0, br: 1 },            // 1 inhale: the chest swells, nothing else moves
  { dy: 0,  lx: -1, jaw: 0, br: 0 },            // 2 the weight shifts one pace toward you. that is all
  { dy: -2, lx: 4,  jaw: 1, br: 1, wind: 1 },   // 3 wind-up: rear back and away
  { dy: 1,  lx: -7, jaw: 2, br: 0, hit: 1 },    // 4 strike: everything forward
  { dy: 4,  lx: -2, jaw: 2, br: 0, fall: 1 },   // 5 crumple
];

function monShadow(g, w, dead) {
  const sw = dead ? w + 10 : w;
  for (let i = 0; i < sw; i += 2)
    g.r(MCX - (sw >> 1) + i, MGROUND + ((i & 2) ? 1 : 0), 1, 1, "#151020");
}

// ── body plans ───────────────────────────────────────────────────────────────────────────
// Each returns an ANCHOR MAP the species' detail hook draws onto — ears, tusks, staves, dripping weed —
// so a plan is a chassis and a species is a chassis plus a soul.

/** quadruped beast: body slab on four legs, a head with a working jaw, a tail. */
function planQuad(g, S, D, ps, f) {
  const bl = D.bl, bh = D.bh + (ps.br ? 1 : 0);
  const by = FY - D.leg - bh + ps.dy;
  const bx = MCX - (bl >> 1) - 6 + ps.lx;
  // far legs first, one tone down
  const P = S.P, Q = dim(S.P);
  const legAt = (x, R2, bend) => {
    g.r(x - 1, by + bh - 2, D.lw + 2, D.leg + 2 - (ps.fall ? 3 : 0), R2.o);
    g.r(x, by + bh - 2, D.lw, D.leg + 1 - (ps.fall ? 3 : 0), R2.m);
    g.r(x, by + bh - 2, 1, D.leg, R2.l);
    g.r(x - bend - 1, FY - 2, D.lw + bend + 2, 3, R2.o);     // paw, toes forward
    g.r(x - bend, FY - 2, D.lw + bend, 2, R2.m);
  };
  legAt(bx + 3 + (ps.hit ? -3 : 0), Q, 2);
  legAt(bx + bl - D.lw - 2 + (ps.wind ? 2 : 0), Q, 1);
  // the body: rounded slab with a spine ridge
  const spans = [];
  for (let j = 0; j < bh; j++) {
    const rr = Math.min(j, bh - 1 - j);
    const ins = rr === 0 ? 3 : rr === 1 ? 1 : 0;
    spans.push([ins, bl - ins * 2]);
  }
  g.rows(bx, by, spans, P);
  g.r(bx + 3, by + 1, bl - 8, 2, P.l);                        // lit back
  g.r(bx + 2, by + bh - 3, bl - 5, 2, P.d);                   // belly shadow
  // near legs
  legAt(bx + 5 + (ps.hit ? -4 : 0), P, 3);
  legAt(bx + bl - D.lw - 5 + (ps.wind ? 3 : 0), P, 1);
  // head: forward of the body, dropped when striking
  const hh = D.hh, hw = D.hw;
  const hx = bx - hw + 3 - (ps.hit ? 4 : 0);
  const hy = by - (hh >> 2) + (ps.hit ? 6 : ps.jaw ? 1 : 0);
  g.rows(hx, hy, Array.from({ length: hh }, (_, j) => {
    const rr = Math.min(j, hh - 1 - j);
    return [rr === 0 ? 2 : rr === 1 ? 1 : 0, hw - (rr === 0 ? 4 : rr === 1 ? 2 : 0)];
  }), P);
  g.r(hx + 2, hy + 1, hw - 6, 2, P.l);
  // the maw: a wedge cut out of the head's lower-left, deeper as jaw opens
  const maw = ps.jaw * 2;
  if (maw) {
    g.r(hx - 1, hy + hh - 4, 7 + maw, 3 + maw, P.o);
    g.r(hx, hy + hh - 3 - (maw >> 1), 6 + maw, 2 + maw, "#1c0a10");
    for (let k = 0; k < 3; k++) g.r(hx + 1 + k * 2, hy + hh - 3 - (maw >> 1), 1, 1, "#e8dcc0");  // teeth
  }
  g.orb(hx + 4, hy + 3, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  // tail off the rump
  const tx = bx + bl - 2, ty = by + 2;
  g.taper(tx, ty - (ps.wind ? 3 : 1), 1, -1, D.tail, D.tw, P);
  return { bx, by, bl, bh, hx, hy, hw, hh, P };
}

/** small biped: a head too big for its body, hunched over two quick legs, one working arm. */
function planGrot(g, S, D, ps, f) {
  const P = S.P, T = S.T;
  const bw = D.bw + (ps.br ? 1 : 0), bh = D.bh;
  const by = FY - D.leg - bh + ps.dy;
  const bx = MCX - (bw >> 1) + ps.lx;
  // legs: short, springy, splayed on the strike
  const leg = (x, R2, splay) => {
    g.r(x - 1, by + bh - 3, 5, D.leg + 4 - (ps.fall ? 3 : 0), R2.o);
    g.r(x, by + bh - 3, 3, D.leg + 3 - (ps.fall ? 3 : 0), R2.m);
    g.r(x - splay - 1, FY - 2, 6 + splay, 3, R2.o);
    g.r(x - splay, FY - 2, 4 + splay, 2, R2.m);
  };
  leg(bx + 1 + (ps.hit ? -2 : 0), dim(P), 2);
  leg(bx + bw - 5 + (ps.wind ? 2 : 0), P, 1);
  // the hunched body
  g.rows(bx, by, Array.from({ length: bh }, (_, j) => {
    const rr = Math.min(j, bh - 1 - j);
    return [rr === 0 ? 2 : rr === 1 ? 1 : 0, bw - (rr === 0 ? 4 : rr === 1 ? 2 : 0)];
  }), P);
  g.r(bx + 2, by + 1, bw - 6, 2, P.l);
  // the head: half the creature, thrust forward
  const hw = D.hw, hh = D.hh;
  const hx = bx - (hw >> 1) - 2 - (ps.hit ? 4 : 0) + (ps.wind ? 3 : 0);
  const hy = by - hh + 4 + (ps.jaw ? 1 : 0);
  g.rows(hx, hy, Array.from({ length: hh }, (_, j) => {
    const rr = Math.min(j, hh - 1 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, hw - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  g.r(hx + 2, hy + 1, hw - 7, 2, P.l);
  g.r(hx + hw - 4, hy + 2, 3, hh - 5, P.d);
  const maw = ps.jaw * 2;
  g.r(hx + 1, hy + hh - 4, 8 + maw, 2 + maw, P.o);
  g.r(hx + 2, hy + hh - 3, 6 + maw, maw + 1, "#1c0a10");
  if (maw) for (let k = 0; k < 3; k++) g.r(hx + 2 + k * 2, hy + hh - 3, 1, 1, "#e8dcc0");
  g.orb(hx + 3, hy + 4, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  // the weapon arm: cocked on wind-up, thrown on strike
  const ax = bx + 2, ay = by + 3;
  const wx = ps.hit ? bx - 12 : ps.wind ? bx + bw + 2 : bx - 6;
  const wy = ps.hit ? by + 4 : ps.wind ? by - 4 : by + 6;
  g.tube(ax, ay, wx, wy, 3, P);
  g.r(wx - 1, wy - 1, 4, 4, P.o);
  g.r(wx, wy, 2, 2, P.m);
  return { bx, by, bw, bh, hx, hy, hw, hh, wx, wy, P, T };
}

/** the wall: a huge trapezoid torso on stump legs, a small sunken head, one weapon arm. */
function planHulk(g, S, D, ps, f) {
  const P = S.P, T = S.T;
  const sw = D.sw + (ps.br ? 2 : 0), hip = D.hip, bh = D.bh;
  const by = FY - D.leg - bh + ps.dy;
  const cx2 = MCX + 2 + ps.lx;
  // stump legs
  const leg = (x, R2) => {
    g.r(x - 1, FY - D.leg - 2, D.lw + 2, D.leg + 2 - (ps.fall ? 4 : 0), R2.o);
    g.r(x, FY - D.leg - 2, D.lw, D.leg + 1 - (ps.fall ? 4 : 0), R2.m);
    g.r(x, FY - D.leg - 2, 2, D.leg, R2.l);
    g.r(x - 3, FY - 2, D.lw + 4, 3, R2.o);
    g.r(x - 2, FY - 2, D.lw + 2, 2, R2.m);
  };
  leg(cx2 - (hip >> 1) - 2, dim(P));
  leg(cx2 + 2, P);
  // torso: shoulders wide, hips narrow — width row-lerped
  const spans = [];
  for (let j = 0; j < bh; j++) {
    const u = j / (bh - 1);
    const w = Math.round(sw + (hip - sw) * u);
    spans.push([Math.round((sw - w) / 2) + Math.round(ps.lx * 0.2 * (1 - u)), w]);
  }
  g.rows(cx2 - (sw >> 1), by, spans, P);
  g.r(cx2 - (sw >> 1) + 3, by + 1, (sw >> 1), 3, P.l);
  g.r(cx2 + (sw >> 2), by + 3, (sw >> 2) + 2, bh - 8, P.d);
  g.r(cx2 - (sw >> 1) + 2, by + bh - 3, sw - 8, 2, P.d);
  // the head, sunk between the shoulders
  const hw = D.hw, hh = D.hh;
  const hx = cx2 - (sw >> 1) - (ps.hit ? 5 : 0) + (ps.wind ? 3 : 0);
  const hy = by - hh + 3 + (ps.jaw ? 1 : 0);
  g.rows(hx, hy, Array.from({ length: hh }, (_, j) => {
    const rr = Math.min(j, hh - 1 - j);
    return [rr === 0 ? 2 : rr === 1 ? 1 : 0, hw - (rr === 0 ? 4 : rr === 1 ? 2 : 0)];
  }), P);
  g.r(hx + 1, hy + 1, hw - 5, 1, P.l);
  const maw = ps.jaw;
  if (maw) {
    g.r(hx, hy + hh - 3, 6 + maw, 2 + maw, P.o);
    g.r(hx + 1, hy + hh - 2, 4 + maw, maw, "#1c0a10");
  }
  g.orb(hx + 2, hy + 3, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  // the weapon arm — a JOINTED limb: thick upper arm to an elbow, leaner forearm to a fist.
  // A uniform shoulder-to-shin tube reads as a noodle; the elbow break is what makes the
  // mass read as muscle. Idle keeps the fist at belt height — coiled, not dangling.
  const shx = cx2 - (sw >> 1) + 3, shy = by + 4;
  g.r(shx - 3, shy - 3, 8, 6, P.m);                                    // shoulder boulder
  g.r(shx - 3, shy - 3, 8, 2, P.l);
  const ex = ps.hit ? shx - 9 : ps.wind ? shx + 3 : shx - 4;           // the elbow
  const ey = ps.hit ? by + (bh >> 1) : ps.wind ? by - 8 : shy + (bh >> 1);
  const wx = ps.hit ? cx2 - (sw >> 1) - 14 : ps.wind ? cx2 + (sw >> 1) + 4 : shx - 7;
  const wy = ps.hit ? FY - 8 : ps.wind ? by - 12 : by + bh - 8;
  g.tube(shx, shy, ex, ey, D.aw + 1, P);                               // upper arm, thick
  g.tube(ex, ey, wx, wy, Math.max(2, D.aw - 1), P);                    // forearm, leaner
  g.r(ex - 1, ey - 1, 3, 3, P.d);                                      // elbow shadow pins the joint
  g.r(wx - 2, wy - 2, D.aw + 4, D.aw + 3, P.o);                        // the fist
  g.r(wx - 1, wy - 1, D.aw + 2, D.aw + 1, P.m);
  g.r(wx - 1, wy - 1, D.aw + 2, 1, P.l);                               // knuckle light
  // the OFF arm — same jointed build on the far flank, dimmed
  const DP = dim(P);
  const shx2 = cx2 + (sw >> 1) - 4, ey2 = by + 5 + (bh >> 1);
  g.tube(shx2, by + 5, shx2 + 3, ey2, D.aw, DP);
  g.tube(shx2 + 3, ey2, shx2, by + bh - 6, Math.max(2, D.aw - 1), DP);
  g.r(shx2 - 2, by + bh - 8, D.aw + 3, D.aw + 2, DP.o);
  g.r(shx2 - 1, by + bh - 7, D.aw + 1, D.aw, DP.m);
  return { cx: cx2, by, sw, hip, bh, hx, hy, hw, hh, wx, wy, P, T };
}

/** floater: an airborne mass with a bob, no legs, a smaller shadow — wings or nothing by species. */
function planFly(g, S, D, ps, f) {
  const P = S.P;
  const bob = [0, -2, 0, 1][f & 3] + ps.dy - 14 + (ps.fall ? 12 : 0);
  const bw = D.bw + (ps.br ? 1 : 0), bh = D.bh;
  const by = FY - D.alt - bh + bob;
  const bx = MCX - (bw >> 1) - 4 + ps.lx;
  const spans = [];
  for (let j = 0; j < bh; j++) {
    const rr = Math.min(j, bh - 1 - j);
    const ins = rr === 0 ? 3 : rr === 1 ? 1 : 0;
    spans.push([ins, bw - ins * 2]);
  }
  // `plain` species own their whole silhouette — no chassis mass, no chassis face
  if (!D.plain) {
    g.rows(bx, by, spans, P);
    g.r(bx + 2, by + 1, bw - 6, 2, P.l);
    g.r(bx + 2, by + bh - 2, bw - 5, 1, P.d);
    const maw = ps.jaw;
    if (maw) {
      g.r(bx, by + bh - 5, 5 + maw, 2 + maw, P.o);
      g.r(bx + 1, by + bh - 4, 3 + maw, maw, "#1c0a10");
    }
    g.orb(bx + 3, by + (bh >> 1) - 2, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  }
  return { bx, by, bw, bh, bob, P };
}

/** standing caster: a bell robe, a head under a hood or hat, a staff arm that reaches on the strike. */
function planRobe(g, S, D, ps, f) {
  const P = S.P, T = S.T;
  const hem = D.hem, top2 = D.top, rh = D.rh;
  const by = FY - rh + ps.dy + 1;
  const cx2 = MCX + 2 + ps.lx;
  const spans = [];
  for (let j = 0; j < rh; j++) {
    const u = j / (rh - 1);
    const w = Math.round(top2 + (hem - top2) * u * u);        // bell curve: narrow → flare
    const swy = j > rh - 5 ? [0, 1, 0, -1][f & 3] : 0;        // the hem breathes
    spans.push([Math.round((hem - w) / 2) + swy, w]);
  }
  g.rows(cx2 - (hem >> 1), by, spans, P);
  g.r(cx2 - (top2 >> 1) + 1, by + 1, 3, rh - 6, P.l);
  g.r(cx2 + (top2 >> 1) - 2, by + 3, 3, rh - 8, P.d);
  for (let i = 0; i < hem; i += 3) g.r(cx2 - (hem >> 1) + i, by + rh - 2, 1, 2, P.d);  // hem folds
  // head over the collar
  const hw = D.hw, hh = D.hh;
  const hx = cx2 - (hw >> 1) - 2 - (ps.hit ? 3 : 0);
  const hy = by - hh + 3 + (ps.wind ? -2 : 0);
  g.rows(hx, hy, Array.from({ length: hh }, (_, j) => {
    const rr = Math.min(j, hh - 1 - j);
    return [rr === 0 ? 2 : rr === 1 ? 1 : 0, hw - (rr === 0 ? 4 : rr === 1 ? 2 : 0)];
  }), S.F || P);
  g.orb(hx + 3, hy + (hh >> 1) - 1, D.eye + 1, Math.max(1, D.eye - 1), S.eye, (S.F || P).o, f);
  // the staff: planted at idle, raised on wind-up, LEVELLED at the hero on the strike
  const sx = ps.hit ? cx2 - 22 : ps.wind ? cx2 + 8 : cx2 - (hem >> 1) - 4;
  const sy = ps.hit ? by + 6 : ps.wind ? by - 16 : by - 6;
  const ex2 = ps.hit ? cx2 - 4 : ps.wind ? cx2 + 2 : cx2 - (hem >> 1) - 2;
  const ey = ps.hit ? by + 8 : ps.wind ? by - 2 : FY - 1;
  g.seg(ex2 - 1, ey - 1, sx - 1, sy - 1, 3, T.o);
  g.seg(ex2, ey, sx, sy, 1, T.m);
  g.r(sx - 2, sy - 2, 5, 5, T.o);                             // the head of the staff
  g.r(sx - 1, sy - 1, 3, 3, S.glow);
  g.r(sx - 1, sy - 1, 1, 1, "#ffffff");
  if (ps.hit) {                                               // the bolt, mid-flight
    g.d(sx - 12, sy - 1, 8, 3, S.glow, f);
    g.r(sx - 14, sy, 3, 1, "#ffffff");
  }
  g.tube(cx2 - (top2 >> 1), by + 4, ex2 + 1, ey - (ps.hit ? 0 : 8), 3, P);
  return { cx: cx2, by, hem, top: top2, rh, hx, hy, hw, hh, sx, sy, P, T };
}

/** low crawler: a wide flat carapace over rowed legs — spiders, scuttlers, things with too many knees. */
function planCrawl(g, S, D, ps, f) {
  const P = S.P;
  const bw = D.bw, bh = D.bh;
  const by = FY - D.leg - bh + ps.dy + (ps.hit ? 2 : 0);
  const bx = MCX - (bw >> 1) - 2 + ps.lx;
  // legs: three visible pairs, knees ABOVE the shell — the unmistakable crawler silhouette
  for (let k = 0; k < 3; k++) {
    const lx2 = bx + 4 + k * ((bw - 8) >> 1);
    const kx = lx2 - 4 + (f & 1 ? 1 : 0) + (ps.hit ? -2 : 0);
    const ky = by - 4 - (k === 1 ? 2 : 0);
    g.seg(lx2, by + 2, kx, ky, 2, P.o);
    g.seg(kx, ky, kx - 3, FY, 2, P.o);
    g.seg(lx2, by + 2, kx, ky, 1, P.m);
    g.seg(kx, ky, kx - 3, FY, 1, P.m);
    // far pair, dimmed, mirrored a little back
    g.seg(lx2 + 2, by + 3, lx2 + 6, FY, 1, dim(P).m);
  }
  // the carapace
  const spans = [];
  for (let j = 0; j < bh; j++) {
    const rr = Math.min(j, bh - 1 - j);
    const ins = rr === 0 ? 3 : rr === 1 ? 1 : 0;
    spans.push([ins, bw - ins * 2]);
  }
  g.rows(bx, by, spans, P);
  g.r(bx + 3, by + 1, bw - 9, 2, P.l);
  g.r(bx + 2, by + bh - 2, bw - 5, 1, P.d);
  g.orb(bx + 3, by + (bh >> 1) - 1, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  if (ps.jaw) {                                               // fangs part
    g.taper(bx + 1, by + bh - 2, -1, 1, 3, 2, P);
    g.taper(bx + 5, by + bh - 2, 0, 1, 3, 2, P);
  }
  return { bx, by, bw, bh, P };
}

/** segmented slug — leeches and worse: a fat low body that REARS its front third to strike. */
function planSlug(g, S, D, ps, f) {
  const P = S.P;
  const bl = D.bl, bh = D.bh + (ps.br ? 1 : 0);
  const by = FY - bh + ps.dy - 1;
  const bx = MCX - (bl >> 1) - 4 + ps.lx;
  const rear = ps.hit ? 10 : ps.wind ? -2 : [0, 1, 0, 0][f & 3] * 2;
  const spans = [];
  for (let j = 0; j < bh; j++) {
    const rr = Math.min(j, bh - 1 - j);
    spans.push([rr === 0 ? 3 : rr === 1 ? 1 : 0, bl - (rr === 0 ? 6 : rr === 1 ? 2 : 0)]);
  }
  g.rows(bx, by, spans, P);
  if (!D.plain) for (let i = 6; i < bl - 3; i += 5) g.r(bx + i, by + 1, 1, bh - 2, P.d);  // segment rings
  g.r(bx + 3, by + 1, bl - 10, 2, P.l);
  // the reared front
  const fx2 = bx - 6, fy2 = by - rear;
  g.rows(fx2, fy2, Array.from({ length: bh + (rear > 0 ? 8 : 6) - bh }, (_, j) => [j >> 1, 9 - (j >> 1)]), P);
  g.r(fx2 + 1, fy2 + 1, 4, 2, P.l);
  const maw = ps.jaw;
  if (maw) {
    g.r(fx2 - 1, fy2 + 3, 4 + maw, 2 + maw, P.o);
    g.r(fx2, fy2 + 4, 3 + maw, maw, "#2a0812");
    for (let k = 0; k < 3; k++) g.r(fx2 + k, fy2 + 4 + (k & 1), 1, 1, "#e8dcc0");  // the rasp
  }
  g.orb(fx2 + 2, fy2 + 1, D.eye + 1, Math.max(1, D.eye - 1), S.eye, P.o, f);
  return { bx, by, bl, bh, fx: fx2, fy: fy2, P };
}

// ── the fall ─────────────────────────────────────────────────────────────────────────────
// Frame 5 is A BODY LEARNING IT IS DEAD — authored mid-collapse per chassis, not the standing pose with
// a red tint (which is what the first draft shipped, and it read as a blink, not a death). Every one
// pitches TOWARD the hero: he is what killed it.

function fallQuad(g, S, D, f) {
  const P = S.P;
  // forelegs gone: the body tilts nose-down, hind leg still pushing at nothing
  const bl = D.bl, bh = D.bh;
  const bx = MCX - (bl >> 1) - 8;
  for (let i = 0; i < bl; i++) {                              // the slab, slanting nose-first into the dirt
    const y = FY - bh - 8 + Math.round(i / 2.5);              // nose-down slant
    g.r(bx + i, y - 1, 1, bh + 2, P.o);
    g.r(bx + i, y, 1, bh, P.m);
    g.r(bx + i, y, 1, 2, P.l);
  }
  g.tube(bx + bl - 6, FY - bh - 4, bx + bl - 2, FY - 12, D.lw, P);   // the hind leg, up and useless
  g.r(bx + bl - 4, FY - 13, D.lw + 1, 2, P.d);
  g.tube(bx + 8, FY - 6, bx + 2, FY - 1, D.lw, dim(P));       // a foreleg folded under
  // the head, cheek in the road, jaw knocked open
  g.rows(bx - D.hw + 4, FY - D.hh + 2, Array.from({ length: D.hh - 2 }, (_, j) =>
    [Math.min(j, D.hh - 3 - j) === 0 ? 2 : 0, D.hw - (Math.min(j, D.hh - 3 - j) === 0 ? 4 : 0)]), P);
  g.r(bx - D.hw + 5, FY - 4, D.hw - 6, 2, "#1c0a10");         // the slack maw
  for (let k = 0; k < 3; k++) g.r(bx - D.hw + 6 + k * 3, FY - 4, 1, 1, "#cfc4a8");
  g.r(bx - D.hw + 8, FY - D.hh + 5, 3, 1, P.o);               // the eye already a line
  g.taper(bx + bl - 2, FY - bh - 6, 1, 0, D.tail - 2, D.tw, P);      // tail flat along the ground
}

function fallBiped(g, S, D, sw2, bh, f) {
  const P = S.P;
  // knees gone: shins flat on the road, torso pitched forward over them, head hanging, arm to the dirt
  const cx2 = MCX + 1;
  g.r(cx2 - (sw2 >> 1) - 2, FY - 4, sw2 + 6, 4, P.o);          // the folded legs, a low plinth of itself
  g.r(cx2 - (sw2 >> 1) - 1, FY - 3, sw2 + 4, 3, P.d);
  for (let j = 0; j < bh - 6; j++) {                           // the torso, pitched ~40° toward the hero
    const u = j / Math.max(1, bh - 7);
    const w = Math.round(sw2 - u * (sw2 * 0.3));
    const x = cx2 - (w >> 1) - Math.round(u * 10);             // leaning out over the fall
    const y = FY - 4 - (bh - 6) + j + Math.round(u * 3);
    g.r(x - 1, y, w + 2, 1, P.o);
    g.r(x, y, w, 1, P.m);
    g.r(x, y, 1, 1, P.l);
    g.r(x + w - 1, y, 1, 1, P.d);
  }
  // the head, hanging off the pitch — face already gone from it
  const hx = cx2 - (sw2 >> 1) - D.hw + 2, hy = FY - 10;
  g.rows(hx, hy, Array.from({ length: 8 }, (_, j) =>
    [Math.min(j, 7 - j) === 0 ? 2 : 0, D.hw - (Math.min(j, 7 - j) === 0 ? 4 : 0)]), P);
  g.r(hx + 2, hy + 3, D.hw - 6, 1, P.o);
  g.tube(cx2 - (sw2 >> 1) + 2, FY - bh + 4, hx - 2, FY - 2, 3, dim(P));   // the arm, palm to the road
  g.r(hx - 5, FY - 3, 4, 2, P.d);
}

function fallFly(g, S, D, f) {
  const P = S.P;
  // out of the air: the mass on the ground, wings flung up, the last lift streaking above it
  const bw = D.bw + 2, bh = Math.max(6, D.bh - 3);
  const bx = MCX - (bw >> 1) - 4, by = FY - bh;
  g.rows(bx, by, Array.from({ length: bh }, (_, j) => {
    const rr = Math.min(j, bh - 1 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, bw - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  g.rows(bx + bw - 3, by - 8, [[0, 4], [1, 6], [2, 7]], dim(P));       // a wing thrown up
  g.rows(bx - 6, by - 5, [[2, 5], [0, 6]], dim(P));
  g.d(bx + 2, by - 14 - (f & 1) * 2, bw - 2, 3, P.d, f);               // the fall it just finished
  g.r(bx - 3, FY - 1, bw + 8, 1, P.o);                                 // the dust line of impact
}

function fallRobe(g, S, D, f) {
  const P = S.P, T = S.T;
  // the robe folding into itself: hem pooled wide, the head bowing INTO the collapse, staff clattering
  const hem = D.hem + 6, rh = Math.max(10, (D.rh * 3) >> 2) - 4;
  const cx2 = MCX + 2, by = FY - rh + 1;
  for (let j = 0; j < rh; j++) {
    const u = j / (rh - 1);
    const w = Math.round(D.top + (hem - D.top) * u * u);
    g.r(cx2 - (w >> 1) - 1, by + j, w + 2, 1, P.o);
    g.r(cx2 - (w >> 1), by + j, w, 1, j > rh - 4 ? P.d : P.m);
  }
  const hx = cx2 - (D.hw >> 1) - 4, hy = by - 3;                       // the head, bowed to the chest
  g.rows(hx, hy, Array.from({ length: D.hh - 3 }, (_, j) =>
    [Math.min(j, D.hh - 4 - j) === 0 ? 2 : 0, D.hw - (Math.min(j, D.hh - 4 - j) === 0 ? 4 : 0)]), S.F || P);
  g.seg(cx2 - (hem >> 1) - 8, FY - 2, cx2 - (hem >> 1) + 10, FY - 6, 1, T.m);   // the staff, down
  g.r(cx2 - (hem >> 1) - 10, FY - 8, 4, 4, T.o);
  g.d(cx2 - (hem >> 1) - 9, FY - 7, 2, 2, S.glow, f);                  // its light guttering
}

function fallCrawl(g, S, D, f) {
  const P = S.P;
  // the knees quit all at once: shell flat on the road, legs splayed straight out
  const bw = D.bw + 4, bh = Math.max(6, D.bh - 3);
  const bx = MCX - (bw >> 1) - 2, by = FY - bh;
  g.rows(bx, by, Array.from({ length: bh }, (_, j) => {
    const rr = Math.min(j, bh - 1 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, bw - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  for (let k = 0; k < 3; k++) {
    g.seg(bx + 3 + k * (bw >> 2), by + bh - 2, bx - 6 + k * 3, FY - 1, 1, P.m);       // legs flat, near side
    g.seg(bx + bw - 4 - k * 3, by + bh - 2, bx + bw + 5 - k * 2, FY - 1, 1, dim(P).m); // far side
  }
  g.r(bx + 3, by + 2, 2, 1, P.o);                                      // the eyes gone flat
  g.r(bx + 7, by + 3, 2, 1, P.o);
}

function fallSlug(g, S, D, f) {
  const P = S.P;
  const bl = D.bl + 4, bh = Math.max(5, D.bh - 2);
  const bx = MCX - (bl >> 1) - 4;
  g.rows(bx, FY - bh, Array.from({ length: bh }, (_, j) =>
    [Math.min(j, bh - 1 - j) === 0 ? 3 : 0, bl - (Math.min(j, bh - 1 - j) === 0 ? 6 : 0)]), P);
  for (let i = 5; i < bl - 3; i += 5) g.r(bx + i, FY - bh + 1, 1, bh - 2, P.d);
  g.rows(bx - 6, FY - 4, [[1, 6], [0, 8]], P);                          // the front, face-down
  g.r(bx - 4, FY - 3, 3, 1, P.o);
}

const FALLS = {
  quad: fallQuad,
  grot: (g, S, D, f) => fallBiped(g, S, D, D.bw, D.bh + 4, f),
  hulk: (g, S, D, f) => fallBiped(g, S, D, D.sw - 6, D.bh, f),
  fly: fallFly,
  robe: fallRobe,
  crawl: fallCrawl,
  slug: fallSlug,
};

const PLANS = { quad: planQuad, grot: planGrot, hulk: planHulk, fly: planFly, robe: planRobe,
                crawl: planCrawl, slug: planSlug };

// ── the species ──────────────────────────────────────────────────────────────────────────
// A species = a chassis (plan), a hide (P) and trim (T) ramp, an eye, a glow, ONE dims table, and a
// detail hook `dt(g, a, ps, f, heat)` that paints the parts no chassis could guess. Elite-rank species
// are not "the same but bigger" — they are the realm's second, meaner answer to the same family slot.
function sp(name, plan, P, T, eye, glow, d, dt, dead) {
  return { name, plan, P, T, eye, glow, d, dt, dead };
}

// GRIM PASS — every hide is pulled toward the dark before it is ever used. The bestiary's first draft
// ran bright and it read as a children's book; one transform here keeps all thirty palettes in the same
// cold register as the knight without re-authoring a single hue relationship.
const grim = (P) => ({ o: tint(P.o, "#020208", 0.45), d: tint(P.d, "#0c0a16", 0.40),
                       m: tint(P.m, "#14121f", 0.38), l: tint(P.l, "#1c1929", 0.32),
                       s: tint(P.s, "#282436", 0.25) });
const mr = (...a) => grim(ramp(...a));

// realm hides
const GW_FUR  = mr("#241408", "#54341c", "#7e522c", "#a87944", "#d4ab6e"); // greenwood russet
const GW_GREY = mr("#181c22", "#3a4450", "#5d6b7a", "#8697a6", "#b8c8d4"); // wolf smoke
const GW_HIDE = mr("#1c1410", "#463024", "#6a4a34", "#93684a", "#c09a70"); // boar umber
const GW_MOSS = mr("#101c10", "#2c4426", "#48663a", "#6c8f54", "#a0c47e"); // troll moss
const GW_LEAF = mr("#122208", "#2f5215", "#4c8024", "#74b23e", "#aede6e"); // sprite leaf
const GW_BARK = mr("#180f08", "#3c281a", "#5c422c", "#806044", "#a98a64"); // shaman bark
const FN_LCH  = mr("#160c14", "#3c1e30", "#5c3448", "#845066", "#b07e8c"); // leech bruise
const FN_TOAD = mr("#0f1c14", "#2a4a30", "#417048", "#619a62", "#8fc488"); // croaker green
const FN_MIRE = mr("#121710", "#333d28", "#525f3c", "#748356", "#a2b07c"); // lurker weed
const FN_SNAP = mr("#101408", "#2e3a16", "#4c5c24", "#6e8038", "#9cae5c"); // snapjaw scale
const FN_WISP = mr("#0c1420", "#22405c", "#3f6f94", "#68a4c8", "#a8dcf0"); // wisp glowflesh
const FN_HAG  = mr("#161020", "#3a2c48", "#5a476c", "#7f6a92", "#ab97bc"); // witch dusk
const CR_BAT  = mr("#14101c", "#342a44", "#544668", "#78688e", "#a495b8"); // bat felt
const CR_SPID = mr("#0e0e12", "#2a2a34", "#464653", "#6a6a7c", "#9494a8"); // spider slate
const CR_GOL  = mr("#15181c", "#3c4348", "#636d74", "#8c979e", "#bcc8ce"); // granite
const CR_OGRE = mr("#1a1512", "#443830", "#6a594c", "#93806a", "#c0ac92"); // ogre leather
const CR_GEO  = mr("#140e1e", "#382a52", "#5c4884", "#8168b4", "#af92e2"); // geode violet
const CR_STRM = mr("#0e141e", "#2a3c56", "#456186", "#6689b2", "#96bade"); // storm slate-blue
const AS_HND  = mr("#140a06", "#38180c", "#5c2a12", "#84421a", "#b06428"); // hound char-ember
const AS_GHL  = mr("#16130f", "#3c352c", "#5f574a", "#847b6a", "#aca394"); // ash grey
const AS_MAG  = mr("#170c08", "#401e10", "#66301a", "#8e4826", "#c06a36"); // magma crust
const AS_REV  = mr("#14161c", "#363c48", "#585f70", "#7d8598", "#a8b0c2"); // revenant iron
const AS_IMP  = mr("#1c0a08", "#4a1a10", "#762c18", "#a44424", "#d46a36"); // imp brick
const AS_PYR  = mr("#1c1008", "#48280e", "#744018", "#a05e24", "#cc8438"); // pyromancer ochre
const NT_SHD  = mr("#0c0a16", "#241f3c", "#3d3660", "#585088", "#7f78b2"); // shade violet
const NT_BONE = mr("#181410", "#4a4238", "#7a7060", "#a89a86", "#d8ccb4"); // old bone
const NT_HUSK = mr("#141008", "#38301c", "#5a4e2e", "#7e6e44", "#a89662"); // husk tallow
const NT_KNT  = mr("#10121a", "#2c3244", "#4a5268", "#6c7590", "#969fba"); // crypt steel
const NT_EYE  = mr("#160c18", "#3c2440", "#613e66", "#885c8e", "#b488ba"); // veil flesh
const NT_LICH = mr("#0e141a", "#283a48", "#436074", "#6288a0", "#92bcd0"); // lich shroud

const SPECIES = [
  [ // ── GREENWOOD — the old wood; nothing here is merely an animal. Fae, fiends and worse,
    //    wearing the wood's shapes badly
    [
      sp("redcap", "grot", GW_BARK, GW_BARK, "#ff6a5a", "#b6ff6a",
        { bw: 16, bh: 14, leg: 7, hw: 11, hh: 10, eye: 2 },
        (g, a, ps, f) => {
          // the murderous fae of the border ballads: iron boots, a butcher's cleaver, and a cap
          // kept red the only way a cap stays red
          const RC = ramp("#2c0a12", "#5a1420", "#8a2430", "#b43848", "#e06a6a");
          const IR = ramp("#14161c", "#242832", "#3a4050", "#525a70", "#8a92a8");
          g.rows(a.hx - 1, a.hy - 4, [[2, 9], [1, 11], [0, 13], [0, 13]], RC);   // the sodden cap
          g.taper(a.hx + a.hw - 1, a.hy - 6, 1, -1, 6, 3, RC);                   // its point, flopped back
          g.r(a.hx, a.hy - 1, a.hw - 3, 1, RC.d);                                // brim shadow on the eyes
          g.taper(a.hx - 3, a.hy + 4, -1, 0, 4, 2, a.P);                         // the hooked nose
          g.r(a.hx - 1, a.hy + a.hh - 3, 4, 1, "#0c0a10");                       // a thin, joyless mouth
          g.r(a.wx - 4, a.wy - 6, 7, 8, IR.m);                                   // the CLEAVER at the fist
          g.r(a.wx - 4, a.wy - 6, 7, 1, IR.l);
          g.r(a.wx - 4, a.wy - 6, 1, 8, "#c8d4dc");                              // the edge, kept keen
          g.r(a.wx - 4, a.wy + 1, 2, 1, "#6a1420");                              // old blood on the corner
          g.r(a.bx, FY - 3, 5, 3, IR.d);                                         // the iron boots
          g.r(a.bx + a.bw - 5, FY - 3, 5, 3, IR.o);
        }),
      sp("barghest", "quad", ramp("#0a0c12", "#181c26", "#262c3a", "#3a4252", "#5a6478"), GW_GREY, "#ff7a1a", "#ff9e2e",
        { bl: 34, bh: 15, leg: 12, lw: 4, hw: 16, hh: 12, eye: 3, tail: 11, tw: 3 },
        (g, a, ps, f) => {
          // the death-omen hound: coal-black, horned, smoking at the edges — a dog only in outline
          g.taper(a.hx + 3, a.hy - 4, 0, -1, 5, 2, a.P);                   // horns, swept back
          g.taper(a.hx + 8, a.hy - 5, 1, -1, 6, 2, a.P);
          g.r(a.hx - 2, a.hy + a.hh - 5, 2, 4, "#f4f4f4");                 // fangs past the lip
          g.r(a.hx + 1, a.hy + a.hh - 4, 1, 3, "#e8e0d0");
          for (let i = 0; i < 4; i++)                                      // spine spurs breaking the hide
            g.taper(a.bx + 6 + i * 6, a.by - 2, 0, -1, 3 + (i & 1), 2, a.P);
          g.d(a.bx + a.bl - 6, a.by - 4 - (f & 1), 4, 4, "#20242e", f);    // it SMOKES at the edges
          g.d(a.hx - 4, a.hy - 2 + (f & 1), 3, 3, "#20242e", f + 1);
          g.r(a.hx + 3, a.hy + 5, 2, 1, "#ff7a1a");                        // the second ember eye
        }),
    ],
    [
      sp("basilisk", "quad", ramp("#101408", "#242c12", "#38441c", "#4e5e2a", "#78904a"), NT_BONE, "#e8ffb0", "#b6ff6a",
        { bl: 34, bh: 14, leg: 8, lw: 5, hw: 15, hh: 12, eye: 3, tail: 16, tw: 4 },
        (g, a, ps, f) => {
          // the king of serpents, low-slung: a horn-plate crest, scutes, and a gaze that GATHERS
          const CB = ramp("#2c1418", "#54242c", "#7c343c", "#a44850", "#d07a80");
          for (let i = 0; i < 4; i++)                                      // the crest comb
            g.taper(a.hx + 2 + i * 3, a.hy - 3 - (i === 1 ? 2 : 0), 0, -1, 4 + (i === 1 ? 2 : 0), 2, CB);
          g.r(a.hx - 3, a.hy + a.hh - 6, 4, 2, a.P.d);                     // the beaked snout
          g.r(a.hx - 3, a.hy + a.hh - 6, 4, 1, a.P.o);
          for (let i = 0; i < a.bl - 12; i += 4)                           // scale ridge down the spine
            g.r(a.bx + 6 + i, a.by - 1, 2, 2, a.P.d);
          g.r(a.bx + 4, a.by + a.bh - 2, a.bl - 10, 1, "#7a6830");         // pale belly scutes
          if (ps.wind || ps.hit) {                                         // the KILLING GAZE
            g.r(a.hx + 2, a.hy + 3, 4, 3, "#e8ffb0");
            g.d(a.hx - 8, a.hy + 3, 7, 2, "#e8ffb0", f);
          }
        }),
      sp("moss troll", "hulk", GW_MOSS, GW_BARK, "#ffd23a", "#b6ff6a",
        { sw: 34, hip: 20, bh: 30, leg: 12, lw: 9, hw: 13, hh: 11, eye: 2, aw: 6 },
        (g, a, ps, f) => {
          g.seg(a.wx - 2, a.wy - 10, a.wx + 2, a.wy + 4, 6, GW_BARK.o);   // the log club
          g.seg(a.wx - 1, a.wy - 9, a.wx + 2, a.wy + 3, 4, GW_BARK.m);
          g.r(a.wx - 1, a.wy - 8, 2, 3, GW_BARK.l);
          g.d(a.cx - 12, a.by + 2, 10, 5, GW_LEAF.m, f);                  // moss shoulders
          g.d(a.cx + 2, a.by + 8, 8, 4, GW_LEAF.d, f + 1);
          g.r(a.hx, a.hy + a.hh - 3, 6, 1, "#12180c");                    // the mouth: a dark gash, no mirth
          g.r(a.hx + 1, a.hy + a.hh - 5, 2, 3, "#e8dcc0");                // ONE tusk jutting from the underbite
          g.r(a.hx + 1, a.hy + a.hh - 5, 1, 1, "#c8bc9e");                // its worn tip
        }),
    ],
    [
      sp("harpy", "fly", ramp("#16100e", "#2e211c", "#48342a", "#64483a", "#8a6a52"), NT_SHD, "#ffd23a", "#ffb46a",
        { bw: 17, bh: 14, alt: 26, eye: 2, plain: 1 },
        (g, a, ps, f) => {
          // the carrion-woman of the old stories, drawn from the WINGBEAT out: two raised feathered
          // wings, a woman's head and chest, bird's legs ending in spread talons. The first draft
          // laid both wings flat at torso height — it read as a plank through a pigeon.
          const P2 = a.P, W2 = dim(P2);
          const SKIN2 = ramp("#4a4238", "#6a6052", "#8a8070", "#a89e8c", "#d0c8b8");
          const HAIR2 = ramp("#0a0a0c", "#16161a", "#242430", "#36364a", "#50506a");
          const dive = ps.hit ? -6 : 0;                       // the strike is a DIVE, talons first
          const bx = a.bx + dive, by = a.by;
          // wing pose: idle beats slow (up/mid/down), windup rears both wings HIGH, the dive sweeps back.
          // Each pose is a SOLID silhouette — contiguous rows, scalloped only on the trailing edge
          const UP  = [[13, 6], [9, 11], [5, 15], [2, 17], [0, 16], [0, 11], [1, 6]];
          const MID = [[8, 9], [4, 14], [1, 17], [0, 16], [0, 12], [1, 7]];
          const DN  = [[0, 12], [0, 16], [2, 17], [5, 14], [9, 10], [13, 5]];
          const pose = ps.wind ? UP : ps.hit ? MID : [UP, MID, DN][f % 3];
          const lift = pose === UP ? -7 : pose === MID ? -3 : -1;
          const wing = (ox, oy, R5) => {
            pose.forEach((s2, j) => {
              g.r(ox + s2[0], oy + lift + j, s2[1], 1,
                  j === 0 ? R5.l : j < pose.length - 2 ? R5.m : R5.d);
            });
            const last = pose[pose.length - 1];
            for (let s3 = 0; s3 < last[1] + 6; s3 += 3)       // trailing-edge feather scallops
              g.r(ox + last[0] + s3, oy + lift + pose.length, 1, 1, R5.d);
            g.r(ox, oy + lift, 3, 2, R5.o);                   // the wrist bone
          };
          wing(bx + 6, by - 3, W2);                           // far wing, one tone down
          // the torso: a woman's chest narrowing into a feathered waist
          g.rows(bx - 1, by, [[1, 8], [0, 9], [0, 9], [0, 8], [1, 7], [1, 6]], P2);
          g.r(bx, by + 1, 4, 2, SKIN2.m);                     // bare chest above the feathers
          g.r(bx, by + 1, 2, 1, SKIN2.l);
          // the head, thrust forward: pale profile, gold eye, screech, hair STREAMING back
          g.rows(bx - 7, by - 6, [[1, 6], [0, 7], [0, 7], [0, 7], [1, 5]], SKIN2);
          g.rows(bx - 5, by - 9, [[0, 12], [1, 13], [3, 12]], HAIR2);        // hair whipped behind her
          g.d(bx + 5, by - 7 + (f & 1), 6, 2, HAIR2.m, f);                   // its torn ends
          g.r(bx - 6, by - 4, 1, 1, "#ffd23a");                              // the gold eye
          g.r(bx - 7, by - 2, 3, 1 + (ps.wind ? 1 : 0), "#0c0a10");          // the screech
          g.r(bx - 6, by - 2, 1, 1, "#cfc6b8");                              // one tooth in it
          wing(bx + 4, by - 1, P2);                                          // near wing, over the torso
          // feathered hips + a short tail fan
          g.rows(bx + 1, by + 6, [[0, 7], [0, 6], [1, 5]], P2);
          for (let k = 0; k < 3; k++) g.r(bx + 7 + k * 2, by + 7 + k, 3, 1, W2.m);
          // bird legs: thigh, backward knee, shank — ending in SPREAD talons
          for (let k = 0; k < 2; k++) {
            const hx2 = bx + 2 + k * 3, R5 = k ? P2 : W2;
            const fx2 = hx2 - 2 + (ps.hit ? -4 : 0), fy2 = by + 13 + (ps.hit ? 1 : 0);
            g.seg(hx2, by + 8, hx2 + 2, by + 10, 1, R5.m);                   // thigh, back
            g.seg(hx2 + 2, by + 10, fx2, fy2, 1, R5.d);                      // shank, forward
            g.r(fx2 - 2, fy2, 2, 1, "#cfc6b8");                              // fore talons
            g.r(fx2 - 1, fy2 + 1, 1, 1, "#cfc6b8");
            g.r(fx2 + 1, fy2, 1, 1, "#cfc6b8");                              // the rear spur
          }
        }),
      sp("antler shaman", "robe", GW_BARK, GW_BARK, "#eaffb0", "#8dff5a",
        { hem: 22, top: 12, rh: 30, hw: 12, hh: 11, eye: 2 },
        (g, a, ps, f) => {
          g.taper(a.hx + 1, a.hy - 1, -1, -1, 7, 2, NT_BONE);             // the antlers
          g.taper(a.hx + a.hw - 2, a.hy - 1, 1, -1, 7, 2, NT_BONE);
          g.taper(a.hx + 3, a.hy - 3, 0, -1, 4, 1, NT_BONE);
          g.d(a.cx - (a.hem >> 1) + 2, a.by + a.rh - 8, a.hem - 4, 3, GW_LEAF.d, f); // lichen hem
          g.r(a.hx + 2, a.hy + a.hh - 2, a.hw - 5, 1, GW_LEAF.m);         // painted jaw stripe
        }),
    ],
  ],
  [ // ── FEN — the drowned road; soft bodies, patient hunters, marsh light
    [
      sp("the drowned", "slug", NT_HUSK, FN_MIRE, "#9fe8ff", "#7affc0",
        { bl: 24, bh: 6, eye: 1, plain: 1 },
        (g, a, ps, f) => {
          // A DEAD MAN, prone, dragging himself down the road at you. The low base is his sodden torso;
          // everything human about him is drawn here: shoulders, a lolling head, planted forearms, boots
          // trailing in the wet. (Take one had segment rings and read as a caterpillar. Never again.)
          const P2 = NT_HUSK;
          g.rows(a.fx - 3, a.fy - 4, [[1, 8], [0, 10], [0, 10], [1, 9]], P2);      // the shoulders, hunched
          g.rows(a.fx - 5, a.fy - 9, [[2, 5], [1, 7], [0, 8], [0, 8], [1, 6]], P2); // the head, hanging
          g.r(a.fx - 4, a.fy - 7, 2, 1, "#050409");                          // sockets full of bog water
          g.r(a.fx - 1, a.fy - 7, 2, 1, "#050409");
          g.r(a.fx - 4, a.fy - 7, 1, 1, "#9fe8ff");                          // lit from somewhere below
          g.r(a.fx - 4, a.fy - 4, 5, 1, P2.o);                               // the slack mouth
          const rch = ps.hit ? 7 : ps.wind ? -2 : (f & 1);                   // the ARMS do the walking
          g.tube(a.fx - 2, a.fy - 2, a.fx - 10 - rch, a.fy + 4, 2, dim(P2));
          g.r(a.fx - 13 - rch, a.fy + 4, 4, 2, P2.d);                        // fingers full of mud
          g.tube(a.fx + 3, a.fy - 1, a.fx - 4, a.fy + 5, 2, P2);
          g.r(a.fx - 6, a.fy + 5, 4, 2, P2.m);
          g.d(a.bx + 6, a.by - 1, a.bl - 12, 2, FN_MIRE.d, f);               // weed across the spine
          g.r(a.bx + a.bl - 7, a.by + 1, 6, 3, dim(WOOL).m);                 // the legs that quit,
          g.r(a.bx + a.bl - 2, a.by + 2, 4, 3, dim(WOOL).d);                 // boots trailing behind
        }),

      sp("grindylow", "grot", FN_MIRE, FN_TOAD, "#9fe8ff", "#7affc0",
        { bw: 16, bh: 13, leg: 8, hw: 16, hh: 13, eye: 3 },
        (g, a, ps, f) => {
          // the bog-strangler that waits under the weed for wrists — bulbous skull, needle teeth,
          // fingers far too long, and a cold lure to bring you close enough
          g.d(a.hx + 2, a.hy - 2, a.hw - 5, 3, FN_MIRE.d, f);                // weed lank over the skull
          const sx3 = a.hx + a.hw - 3;
          g.seg(sx3, a.hy - 1, sx3 + 3, a.hy - 6 + (f & 1), 1, FN_MIRE.m);   // the lure stalk
          g.r(sx3 + 3, a.hy - 8 + (f & 1), 2, 2, "#9fe8ff");                 // its cold light
          g.r(a.hx + 1, a.hy + a.hh - 4, a.hw - 8, 1, "#08131a");            // a lipless slit of a mouth
          for (let k = 0; k < 3; k++)                                        // needle teeth
            g.r(a.hx + 2 + k * 2, a.hy + a.hh - 4, 1, 2, "#d8e8e0");
          for (let k = 0; k < 3; k++) {                                      // the FINGERS, made for wrists
            const fx2 = a.wx - 2 - k * 2 + (ps.hit ? -4 : 0);
            g.seg(a.wx, a.wy, fx2, a.wy + 5 + k, 1, a.P.m);
            g.r(fx2, a.wy + 5 + k, 1, 2, a.P.d);
          }
        }),
    ],
    [
      sp("mire lurker", "hulk", FN_MIRE, FN_MIRE, "#9fe8ff", "#7affc0",
        { sw: 36, hip: 22, bh: 30, leg: 10, lw: 9, hw: 14, hh: 11, eye: 3, aw: 6 },
        (g, a, ps, f) => {
          for (let i = 0; i < 5; i++) {                                    // hanging weed
            const wx2 = a.cx - (a.sw >> 1) + 3 + i * 7;
            g.r(wx2, a.by + 2 + (i & 1) * 3, 2, 8 + (i % 3) * 3, FN_MIRE.d);
            g.r(wx2, a.by + 2, 2, 2, FN_MIRE.o);
          }
          const dy2 = (f & 3) * 2;                                         // a drip falling off the arm
          g.r(a.wx + 1, a.wy + 4 + dy2, 1, 2, FN_WISP.m);
        }),
      sp("knucker", "quad", FN_SNAP, FN_SNAP, "#ffe27a", "#7affc0",
        { bl: 38, bh: 13, leg: 6, lw: 4, hw: 20, hh: 10, eye: 2, tail: 18, tw: 4 },
        (g, a, ps, f) => {
          // the water-wyrm of the fen pools — a lesser dragon that never grew wings, all jaw and sail
          const open = ps.jaw * 3;
          g.rows(a.hx - 10, a.hy + a.hh - 6 - open, [[0, 14], [0, 14]], a.P);       // the long top jaw
          g.rows(a.hx - 10, a.hy + a.hh - 2 + open, [[0, 13], [1, 11]], dim(a.P));  // bottom jaw
          for (let i = 0; i < 5; i++) {
            g.r(a.hx - 9 + i * 3, a.hy + a.hh - 4 - open, 1, 2, "#f0e8d0");
            g.r(a.hx - 8 + i * 3, a.hy + a.hh - 2 + open, 1, 2, "#f0e8d0");
          }
          g.seg(a.hx - 10, a.hy + a.hh + open, a.hx - 14, a.hy + a.hh + 3 + open, 1, a.P.d);   // barbels
          g.seg(a.hx - 8, a.hy + a.hh - 6 - open, a.hx - 11, a.hy + a.hh - 9 - open, 1, a.P.d);
          for (let i = 0; i < 3; i++)                                        // the SAIL: fin spines…
            g.seg(a.bx + 8 + i * 7, a.by - 1, a.bx + 6 + i * 7, a.by - 6 - (i === 1 ? 2 : 0), 1, a.P.d);
          g.rows(a.bx + 6, a.by - 4, [[0, 15], [2, 11]], dim(a.P));          // …and the web between them
          g.d(a.bx + 6, a.by + 2, a.bl - 14, 2, a.P.l, f);                   // wet scale sheen
        }),
    ],
    [
      sp("will-o-wisp", "fly", FN_WISP, FN_WISP, "#ffffff", "#9fe8ff",
        { bw: 7, bh: 5, alt: 24, eye: 2, plain: 1 },
        (g, a, ps, f) => {
          // A CORPSE-LIGHT, not a mascot: cold flame around a hollow, and the small skull the fen
          // refuses to give back. The chassis blob underneath gave it a face; plain kills the face.
          const cx3 = a.bx + (a.bw >> 1), top2 = a.by - 10;
          const lean = [0, 1, 0, -1][f & 3];
          const FLW = [2, 3, 4, 5, 7, 9, 11, 12, 12, 10];
          const spans = FLW.map((w, j) =>
            [cx3 - (w >> 1) + Math.round(lean * (FLW.length - 1 - j) / 4) - (a.bx - 2), w]);
          g.rows(a.bx - 2, top2, spans, FN_WISP);
          for (let j = 3; j < FLW.length - 1; j++) {                      // the cold sheath
            const w2 = Math.max(1, FLW[j] - 5);
            g.r(cx3 - (w2 >> 1) + Math.round(lean * (FLW.length - 1 - j) / 6), top2 + j, w2, 1,
                j > 5 ? "#e8fbff" : FN_WISP.l);
          }
          g.r(cx3 - 2, top2 + 5, 5, 4, "#08131a");                        // the hollow it burns around
          g.r(cx3 - 1, top2 + 5, 3, 3, "#d8d8e0");                        // the skull inside it
          g.r(cx3 - 1, top2 + 6, 1, 1, "#08131a");                        // socket
          g.r(cx3 + 1, top2 + 6, 1, 1, "#08131a");                        // socket
          g.r(cx3 - 1, top2 + 8, 3, 1, "#8a8a96");                        // the jaw, unlit
          g.r(cx3 + 2 + lean, top2 - 3 - (f & 1) * 2, 1, 2, FN_WISP.l);   // an ember tearing off the tip
          g.r(cx3 - 3 - lean, top2 - 1 - ((f + 1) & 1) * 2, 1, 1, "#e8fbff");
          if (ps.hit) g.d(cx3 - 14, top2 + 5, 9, 3, "#e8fbff", f);
        }),
      sp("bog witch", "robe", FN_HAG, GW_BARK, "#b6ff6a", "#7affc0",
        { hem: 24, top: 11, rh: 32, hw: 12, hh: 11, eye: 2 },
        (g, a, ps, f) => {
          g.rows(a.hx - 3, a.hy - 4, [[2, 15], [5, 8], [6, 5], [7, 3]], FN_HAG);   // the drooping hat
          g.r(a.hx - 4, a.hy - 1, 18, 2, FN_HAG.o);                        // brim
          g.taper(a.hx - 4, a.hy + 4, -1, 0, 5, 2, SKIN);                  // the NOSE. it matters.
          g.r(a.cx + (a.hem >> 1) - 3, a.by + a.rh - 10, 4, 5, FN_WISP.d); // potion at the hip
          g.r(a.cx + (a.hem >> 1) - 2, a.by + a.rh - 9, 2, 3, FN_WISP.l);
        }),
    ],
  ],
  [ // ── CRAGS — the cold pass; stone, silk and thunder
    [
      sp("gargoyle", "fly", CR_GOL, CR_GOL, "#ff9e2e", "#9a9aff",
        { bw: 13, bh: 12, alt: 28, eye: 2 },
        (g, a, ps, f) => {
          // cathedral stone that got tired of the roof: horned, muzzled, a spade on its tail
          const up = (f & 1) ? -5 : 2;
          g.rows(a.bx + a.bw - 2, a.by - 3 + up, [[0, 13], [1, 11], [3, 8], [6, 4]], dim(a.P)); // far wing
          g.seg(a.bx + a.bw - 1, a.by - 3 + up, a.bx + a.bw + 9, a.by - 6 + up, 1, dim(a.P).l); // its spar
          g.taper(a.bx + 2, a.by - 4, 0, -1, 4, 2, a.P);                   // horns, forward-curled
          g.taper(a.bx + 6, a.by - 5, 1, -1, 5, 2, a.P);
          g.r(a.bx + 1, a.by + 3, 4, 1, a.P.d);                            // the heavy brow
          g.r(a.bx + 2, a.by + a.bh - 4, 3, 2, a.P.o);                     // the muzzle, pushed out
          g.r(a.bx + 2, a.by + a.bh - 3, 1, 2, "#e8e8f0");                 // one snag tooth
          g.rows(a.bx - 9, a.by - 2 + up, [[0, 10], [1, 8], [3, 5]], a.P); // near wing
          g.taper(a.bx + a.bw - 1, a.by + a.bh - 2, 1, 1, 8, 2, a.P);      // the tail…
          g.r(a.bx + a.bw + 7, a.by + a.bh + 5, 3, 2, a.P.d);              // …and its spade
          for (let k = 0; k < 2; k++)                                      // stone claws tucked under
            g.r(a.bx + 3 + k * 4, a.by + a.bh, 2, 2 + (k & 1), a.P.d);
        }),
      sp("dread weaver", "crawl", CR_SPID, CR_SPID, "#d8fbff", "#9a9aff",
        { bw: 26, bh: 12, leg: 10, eye: 2 },
        (g, a, ps, f) => {
          // a spider grown into an omen: the death's-head on its back is why miners walk out
          g.orb(a.bx + 8, a.by + 2, 2, 2, "#d8fbff", a.P.o, f + 1);        // the extra eyes
          g.orb(a.bx + 12, a.by + 3, 2, 2, "#d8fbff", a.P.o, f + 2);
          g.r(a.bx + a.bw - 9, a.by + 3, 5, 4, "#6e7482");                 // the DEATH'S-HEAD marking, faded
          g.r(a.bx + a.bw - 8, a.by + 4, 1, 1, a.P.o);                     // its sockets
          g.r(a.bx + a.bw - 6, a.by + 4, 1, 1, a.P.o);
          g.r(a.bx + a.bw - 8, a.by + 6, 3, 1, a.P.o);
          g.taper(a.bx + 2, a.by + a.bh - 3, -1, 1, 4, 2, a.P);            // fang chelicerae
          g.taper(a.bx + 5, a.by + a.bh - 2, -1, 1, 3, 2, a.P);
          g.r(a.bx + 3, a.by + a.bh - 2, 1, 2, "#e8f4ff");                 // a venom bead
          if (ps.wind) g.r(a.bx + a.bw + 2, a.by - 6, 1, 6 + a.bh, "#e8f4ff"); // the anchor line
        }),
    ],
    [
      sp("stone golem", "hulk", CR_GOL, CR_GOL, "#8ae9f6", "#8ae9f6",
        { sw: 38, hip: 26, bh: 32, leg: 11, lw: 11, hw: 12, hh: 10, eye: 3, aw: 8 },
        (g, a, ps, f) => {
          const c = ["#3f707c", "#4f8c9a", "#3f707c", "#356470"][f & 3];    // the core BREATHES light
          g.r(a.cx - 4, a.by + 6, 6, 8, a.P.o);
          g.r(a.cx - 3, a.by + 7, 4, 6, c);
          g.r(a.cx - 2, a.by + 9, 2, 2, "#d8fbff");
          g.seg(a.cx - (a.sw >> 1) + 4, a.by + 14, a.cx - 3, a.by + 8, 1, c);   // glow seams
          g.seg(a.cx + 4, a.by + 10, a.cx + (a.sw >> 1) - 6, a.by + 18, 1, c);
          g.r(a.hx - 2, a.hy - 3, a.hw + 2, 3, a.P.d);                     // brow slab
        }),
      sp("pass ogre", "hulk", CR_OGRE, AS_REV, "#ffd23a", "#9a9aff",
        { sw: 40, hip: 24, bh: 32, leg: 12, lw: 10, hw: 15, hh: 13, eye: 2, aw: 7 },
        (g, a, ps, f) => {
          g.seg(a.wx, a.wy - 12, a.wx + 3, a.wy + 5, 7, CR_GOL.o);         // the stone-head club
          g.seg(a.wx + 1, a.wy - 11, a.wx + 3, a.wy + 4, 5, CR_GOL.m);
          g.r(a.wx - 1, a.wy - 12, 7, 6, CR_GOL.o);
          g.r(a.wx, a.wy - 11, 5, 4, CR_GOL.m);
          g.r(a.cx - 8, a.by + a.bh - 8, 16, 4, AS_REV.d);                 // the belt plate
          g.r(a.cx - 3, a.by + a.bh - 7, 4, 2, AS_REV.l);
          g.r(a.hx + 1, a.hy + a.hh - 3, 2, 3, "#e8dcc0");                 // one proud tooth
        }),
    ],
    [
      sp("geode imp", "grot", CR_GEO, CR_GEO, "#d8fbff", "#af92e2",
        { bw: 16, bh: 12, leg: 7, hw: 14, hh: 12, eye: 3 },
        (g, a, ps, f) => {
          g.taper(a.hx + 3, a.hy - 2, 0, -1, 5, 3, CR_GEO);                // crystal crown
          g.taper(a.hx + 8, a.hy - 3, 0, -1, 6, 3, CR_GEO);
          g.taper(a.hx + 12, a.hy - 2, 1, -1, 4, 2, CR_GEO);
          g.r(a.bx + 3, a.by + 2, 3, 3, CR_GEO.s);                         // shard growths
          g.r(a.bx + a.bw - 5, a.by + 5, 2, 2, CR_GEO.s);
          if (ps.hit) { g.r(a.wx - 8, a.wy - 1, 5, 3, CR_GEO.s); g.r(a.wx - 7, a.wy, 3, 1, "#ffffff"); } // thrown shard
        }),
      sp("storm caller", "robe", CR_STRM, CR_GOL, "#ffffff", "#d8fbff",
        { hem: 22, top: 12, rh: 33, hw: 12, hh: 12, eye: 2 },
        (g, a, ps, f) => {
          g.rows(a.hx - 1, a.hy - 3, [[1, 13], [0, 15], [2, 12]], CR_STRM);   // storm hood
          if (ps.hit || ps.wind) {                                         // forked lightning
            const jx = ps.hit ? a.sx - 3 : a.sx;
            g.seg(jx, a.sy - 8, jx - 4, a.sy - 3, 1, "#e8f8ff");
            g.seg(jx - 4, a.sy - 3, jx + 1, a.sy + 1, 1, "#e8f8ff");
            g.r(jx - 5, a.sy - 4, 2, 2, "#ffffff");
          }
          for (let i = 0; i < 4; i++) g.r(a.cx - (a.hem >> 1) + 3 + i * 5, a.by + a.rh - 6, 1, 1, "#d8fbff"); // static
        }),
    ],
  ],
  [ // ── ASHWAY — the burnt mile; everything glows from inside or has given up glowing
    [
      sp("hellhound", "quad", AS_HND, AS_HND, "#ffd75a", "#ff7a1a",
        { bl: 30, bh: 13, leg: 11, lw: 4, hw: 14, hh: 10, eye: 2, tail: 9, tw: 3 },
        (g, a, ps, f) => {
          // one dog is a dog. TWO heads on one neck is a monster — plus a mane that actually burns
          const c = ["#ff7a1a", "#ffb84a", "#ff7a1a", "#c85a10"][f & 3];    // ember seams pulse
          const h2x = a.hx + 3, h2y = a.hy - 6;
          g.rows(h2x, h2y, [[2, 9], [1, 11], [0, 12], [1, 10], [2, 8]], dim(a.P));  // the SECOND head
          g.r(h2x + 2, h2y + 2, 2, 1, c);                                   // its ember eye
          g.r(h2x - 1, h2y + 3, 3, 1, "#1c0a10");                           // its jaw ajar
          g.r(h2x, h2y + 3, 1, 1, "#f4f4f4");
          g.seg(a.bx + 5, a.by + 3, a.bx + a.bl - 8, a.by + 5, 1, c);
          g.seg(a.bx + 8, a.by + a.bh - 4, a.bx + a.bl - 12, a.by + a.bh - 3, 1, c);
          g.r(a.hx + 2, a.hy + a.hh - 4, 3, 1, c);                          // the lit gullet
          for (let i = 0; i < 4; i++)                                       // the burning mane
            g.r(a.bx + 3 + i * 2, a.by - 3 - ((i + f) & 1), 1, 2 + ((i + f) & 1), ["#ff7a1a", "#ffb84a"][(i + f) & 1]);
          g.r(a.bx + a.bl - 4, a.by - 2 - (f & 1), 1, 2, c);                // sparks off the tail
        }),
      sp("ash ghoul", "grot", AS_GHL, AS_GHL, "#ff5a24", "#ff7a1a",
        { bw: 18, bh: 16, leg: 10, hw: 13, hh: 12, eye: 2 },
        (g, a, ps, f) => {
          for (let k = 0; k < 4; k++) g.taper(a.wx - 1 + k * 2, a.wy + 2, -1, 1, 5, 1, NT_BONE); // the CLAWS
          g.r(a.hx + 2, a.hy + 2, a.hw - 6, 1, a.P.d);                      // sunken brow
          g.r(a.bx + 2, a.by + 3, 1, a.bh - 6, a.P.d);                      // showing ribs
          g.r(a.bx + 4, a.by + 4, 1, a.bh - 8, a.P.d);
          g.d(a.bx - 2, a.by - 3, a.bw + 4, 2, AS_GHL.l, f);                // ash falling off it
        }),
    ],
    [
      sp("magma brute", "hulk", AS_MAG, AS_MAG, "#ffd75a", "#ff7a1a",
        { sw: 38, hip: 24, bh: 31, leg: 11, lw: 10, hw: 13, hh: 10, eye: 2, aw: 8 },
        (g, a, ps, f) => {
          const c = ["#ff9e2e", "#ffd75a", "#ff9e2e", "#e07018"][f & 3];    // lava in the cracks
          g.seg(a.cx - (a.sw >> 1) + 5, a.by + 5, a.cx - 2, a.by + 12, 1, c);
          g.seg(a.cx + 2, a.by + 8, a.cx + (a.sw >> 1) - 7, a.by + 16, 1, c);
          g.seg(a.cx - 6, a.by + 16, a.cx + 3, a.by + 24, 1, c);
          g.r(a.wx - 1, a.wy - 1, 3, 3, c);                                 // molten fist
          g.d(a.cx - 6, a.by - 4, 12, 2, AS_GHL.m, f);                      // smoke off the shoulders
        }),
      sp("iron revenant", "hulk", AS_REV, AS_REV, "#8ae9f6", "#d8fbff",
        { sw: 34, hip: 22, bh: 32, leg: 12, lw: 9, hw: 12, hh: 11, eye: 3, aw: 6 },
        (g, a, ps, f) => {
          g.seg(a.wx - 2, a.wy - 14, a.wx + 1, a.wy + 6, 3, AS_REV.o);      // the greatsword
          g.seg(a.wx - 1, a.wy - 13, a.wx + 1, a.wy + 5, 1, AS_REV.l);
          g.r(a.wx - 4, a.wy - 2, 8, 2, AS_REV.o);                          // crossguard
          g.r(a.hx + 2, a.hy + 4, a.hw - 6, 2, "#8ae9f6");                  // the empty visor glow
          g.r(a.hx + 3, a.hy + 4, 1, 1, "#ffffff");
          g.r(a.cx - 10, a.by + 6, 8, 10, AS_REV.d);                        // dented breastplate
          g.r(a.cx - 9, a.by + 7, 3, 3, AS_REV.o);
          // horned pauldrons with MASS — the old 2px spikes read as radio aerials
          g.rows(a.cx - (a.sw >> 1) - 2, a.by - 4, [[2, 2], [1, 3], [0, 5]], AS_REV);
          g.rows(a.cx + (a.sw >> 1) - 3, a.by - 4, [[0, 2], [0, 3], [0, 5]], AS_REV);
        }),
    ],
    [
      sp("fire imp", "fly", AS_IMP, AS_IMP, "#ffd75a", "#ff7a1a",
        { bw: 14, bh: 13, alt: 20, eye: 2 },
        (g, a, ps, f) => {
          const up = (f & 1) ? -4 : 1;
          g.rows(a.bx + a.bw - 2, a.by - 1 + up, [[0, 10], [2, 7], [4, 4]], AS_IMP);   // scorched wings
          g.rows(a.bx - 7, a.by + up, [[0, 8], [1, 6], [3, 3]], dim(AS_IMP));
          g.taper(a.bx + 2, a.by - 2, -1, -1, 4, 2, a.P);                   // horns
          g.taper(a.bx + a.bw - 3, a.by - 2, 1, -1, 4, 2, a.P);
          g.taper(a.bx + a.bw + 1, a.by + a.bh - 2, 1, 1, 5, 2, a.P);       // barbed tail
          if (ps.hit) { g.r(a.bx - 11, a.by + 4, 4, 4, "#ff7a1a"); g.r(a.bx - 10, a.by + 5, 2, 2, "#ffd75a"); } // fireball
        }),
      sp("pyromancer", "robe", AS_PYR, AS_MAG, "#ffd75a", "#ff9e2e",
        { hem: 23, top: 12, rh: 32, hw: 12, hh: 11, eye: 2 },
        (g, a, ps, f) => {
          g.rows(a.hx, a.hy - 2, [[2, 10], [0, 14], [1, 12]], AS_PYR);      // the cowl
          const c = ["#ff9e2e", "#ffd75a"][f & 1];
          g.r(a.cx - (a.hem >> 1) + 2, a.by + 4, 2, a.rh - 10, c);          // burning trim
          g.d(a.hx + 2, a.hy - 6, 8, 3, AS_GHL.m, f);                       // smoke off the cowl
        }),
    ],
  ],
  [ // ── NETHER — the pale road; what walks here forgot how to stop
    [
      sp("grave shade", "fly", NT_SHD, NT_SHD, "#d8fbff", "#7f78b2",
        { bw: 7, bh: 5, alt: 15, eye: 2 },
        (g, a, ps, f) => {
          // A WRAITH with a silhouette: hooded dome, a skirt that tears into streamers, one arm of smoke
          // reaching for the hero. The old dithered rectangle read as "a purple ball" — a bug, not a ghost.
          const cx3 = a.bx + (a.bw >> 1), top2 = a.by - 8;
          g.rows(cx3 - 7, top2, [
            [4, 6], [2, 10], [1, 12], [0, 14], [0, 14], [0, 14], [0, 14],   // the hooded dome
            [0, 14], [1, 13], [1, 12], [2, 11],
          ], NT_SHD);
          g.r(cx3 - 5, top2 + 2, 3, 4, NT_SHD.l);                           // moonlit crown
          for (let k = 0; k < 4; k++) {                                     // the skirt, torn to streamers
            const sx2 = cx3 - 6 + k * 4, ln = 5 + ((k + f) % 3) * 2;
            g.r(sx2 - 1, top2 + 11, 4, 2, NT_SHD.o);
            g.r(sx2, top2 + 11, 2, ln, NT_SHD.m);
            g.r(sx2, top2 + 10 + ln, 2, 1, NT_SHD.d);
          }
          g.r(cx3 - 4, top2 + 4, 3, 5, "#050409");                          // the hood's void…
          g.r(cx3 - 3, top2 + 5, 1, 3, "#d8fbff");                          // …and the long eyes in it
          g.r(cx3 + 1, top2 + 5, 1, 3, "#d8fbff");
          const rx2 = ps.hit ? cx3 - 16 : cx3 - 11;                         // the reaching arm
          g.seg(cx3 - 5, top2 + 8, rx2, top2 + 6 + (f & 1), 2, NT_SHD.m);
          g.taper(rx2, top2 + 5 + (f & 1), -1, 0, 4, 2, NT_SHD);            // fingers of smoke
          g.d(cx3 + 5, top2 + 3, 4, 8, NT_SHD.d, f);                        // it frays where it ends
        }),
      sp("bone scuttler", "crawl", NT_BONE, NT_BONE, "#7f78b2", "#9a9aff",
        { bw: 24, bh: 11, leg: 9, eye: 2 },
        (g, a, ps, f) => {
          g.rows(a.bx - 6, a.by - 2, [[1, 8], [0, 10], [0, 10], [1, 8]], NT_BONE);   // it wears a SKULL
          g.r(a.bx - 4, a.by, 2, 2, "#0c0a16");                             // socket
          g.r(a.bx, a.by, 2, 2, "#0c0a16");
          g.r(a.bx - 4, a.by, 1, 1, "#9a9aff");                             // the light inside it
          for (let i = 0; i < 3; i++) g.r(a.bx - 5 + i * 3, a.by + 3, 2, 1, NT_BONE.d);  // teeth line
          for (let i = 0; i < a.bw - 8; i += 4) g.r(a.bx + 4 + i, a.by - 1, 1, 2, NT_BONE.l); // vertebrae
        }),
    ],
    [
      sp("flesh husk", "hulk", NT_HUSK, NT_HUSK, "#b6ff6a", "#7f78b2",
        { sw: 32, hip: 22, bh: 30, leg: 11, lw: 9, hw: 13, hh: 12, eye: 2, aw: 6 },
        (g, a, ps, f) => {
          g.seg(a.cx - 8, a.by + 4, a.cx - 2, a.by + 12, 1, NT_HUSK.o);     // the stitching
          g.seg(a.cx + 1, a.by + 14, a.cx + 8, a.by + 20, 1, NT_HUSK.o);
          for (let k = 0; k < 3; k++) g.r(a.cx - 7 + k * 3, a.by + 5 + k * 3, 1, 1, NT_KNT.m); // staples
          g.r(a.cx - 12, a.by + 10, 6, 8, tint(NT_HUSK.m, "#6a8a4a", 0.5)); // the wrong-coloured patch
          g.r(a.hx + a.hw - 3, a.hy + 2, 2, 3, a.P.d);                      // lolling head shadow
        }),
      sp("crypt knight", "hulk", NT_KNT, NT_KNT, "#8ae9f6", "#9a9aff",
        { sw: 32, hip: 21, bh: 32, leg: 12, lw: 8, hw: 12, hh: 11, eye: 3, aw: 5 },
        (g, a, ps, f) => {
          g.seg(a.wx - 1, a.wy - 12, a.wx + 1, a.wy + 5, 3, NT_KNT.o);      // ancient blade
          g.seg(a.wx, a.wy - 11, a.wx + 1, a.wy + 4, 1, NT_KNT.l);
          g.r(a.wx - 3, a.wy - 3, 7, 2, NT_KNT.o);
          g.rows(a.cx + 4, a.by + 8, [[1, 8], [0, 10], [0, 10], [0, 10], [1, 8]], dim(NT_KNT)); // the shield
          g.r(a.cx + 6, a.by + 10, 3, 3, NT_SHD.m);                          // its dead device
          // SOLID helm wings, swept back — the old 2px tapers read as robot antennae
          g.rows(a.hx - 4, a.hy - 3, [[3, 3], [1, 5], [0, 6]], NT_KNT);
          g.rows(a.hx + a.hw - 2, a.hy - 3, [[0, 3], [0, 5], [0, 6]], NT_KNT);
          g.r(a.hx - 2, a.hy - 3, 2, 1, NT_KNT.l);                           // moonlit wing edge
          g.r(a.hx + 2, a.hy + 4, a.hw - 6, 2, "#8ae9f6");                   // visor light
        }),
    ],
    [
      sp("veil eye", "fly", NT_EYE, NT_EYE, "#ffffff", "#b488ba",
        { bw: 18, bh: 16, alt: 24, eye: 2, plain: 1 },
        (g, a, ps, f) => {
          // ONE great lidless eye wrapped in a torn shroud. The veil is the body; the eye is the point.
          // (The chassis box under the old version made it a television with aerials. Never again.)
          const ex2 = a.bx + 1, ey2 = a.by + 1;
          g.rows(ex2 - 3, ey2 - 2, [                                       // the shroud, a ragged cowl
            [5, 8], [3, 13], [2, 16], [1, 18], [0, 20], [0, 20], [0, 20],
            [0, 20], [1, 18], [1, 17], [2, 15], [3, 13],
          ], a.P);
          for (let k = 0; k < 4; k++) {                                     // streamers tearing off below
            const sx2 = ex2 - 1 + k * 5, ln = 3 + ((k + f) % 3) * 2;
            g.r(sx2, ey2 + 9, 2, ln, a.P.m);
            g.r(sx2, ey2 + 8 + ln, 2, 1, a.P.d);
          }
          [[4, 6], [2, 10], [1, 12], [0, 14], [0, 14], [1, 12], [2, 10], [4, 6]]
            .forEach((s, j) => g.r(ex2 + s[0], ey2 + j, s[1], 1, a.P.o));   // the socket's almond mouth
          [[3, 8], [2, 10], [1, 12], [1, 12], [2, 10], [3, 8]]
            .forEach((s, j) => g.r(ex2 + s[0], ey2 + 1 + j, s[1], 1, "#cfc6dc")); // sclera, moon-pale
          g.seg(ex2 + 2, ey2 + 3, ex2 + 4, ey2 + 4, 1, "#7a3244");          // veins crawling inward
          g.seg(ex2 + 12, ey2 + 5, ex2 + 10, ey2 + 4, 1, "#7a3244");
          const dil = ps.wind ? 1 : 0;                                      // it DILATES before the gaze
          g.r(ex2 + 5 - dil, ey2 + 2 - dil, 4 + dil * 2, 4 + dil * 2, "#3c1440");
          g.r(ex2 + 6, ey2 + 2, 2, 4, "#0c0616");                           // slit pupil
          if ((f & 3) === 2 && !ps.wind && !ps.hit)                         // the slow lid, half down
            g.r(ex2 + 1, ey2, 12, 4, a.P.m);
          if (ps.hit) g.d(a.bx - 10, ey2 + 5, 8, 2, "#b488ba", f);          // the gaze made visible
        }),
      sp("lich", "robe", NT_LICH, NT_KNT, "#8ae9f6", "#8ae9f6",
        { hem: 24, top: 12, rh: 34, hw: 12, hh: 12, eye: 3 },
        (g, a, ps, f) => {
          // the head override: a bare skull under the crown
          g.rows(a.hx, a.hy, Array.from({ length: a.hh }, (_, j) => {
            const rr = Math.min(j, a.hh - 1 - j);
            return [rr === 0 ? 2 : rr === 1 ? 1 : 0, a.hw - (rr === 0 ? 4 : rr === 1 ? 2 : 0)];
          }), NT_BONE);
          g.r(a.hx + 2, a.hy + 4, 3, 3, "#0c0a16");                          // sockets…
          g.r(a.hx + 7, a.hy + 4, 3, 3, "#0c0a16");
          g.r(a.hx + 3, a.hy + 5, 1, 1, "#8ae9f6");                          // …lit from far inside
          g.r(a.hx + 8, a.hy + 5, 1, 1, "#8ae9f6");
          for (let i = 0; i < 3; i++) g.r(a.hx + 3 + i * 2, a.hy + a.hh - 2, 1, 2, NT_BONE.d); // teeth
          g.taper(a.hx + 1, a.hy - 1, 0, -1, 4, 2, MATERIALS[5]);            // the CROWN
          g.taper(a.hx + 5, a.hy - 2, 0, -1, 5, 2, MATERIALS[5]);
          g.taper(a.hx + 9, a.hy - 1, 0, -1, 4, 2, MATERIALS[5]);
          const ch = (f & 3);                                                // the phylactery, swinging
          g.seg(a.cx + (a.hem >> 1) - 2, a.by + 8, a.cx + (a.hem >> 1) + 2 - ch, a.by + 16, 1, MATERIALS[5].d);
          g.r(a.cx + (a.hem >> 1) - ch, a.by + 16, 3, 4, MATERIALS[5].m);
          g.r(a.cx + (a.hem >> 1) + 1 - ch, a.by + 17, 1, 1, "#8ae9f6");
        }),
    ],
  ],
];

// ── the realm bosses ─────────────────────────────────────────────────────────────────────
// One per realm, drawn whole — no chassis. A boss fills the box: the chapter climax must be unmistakable
// from across the screen, before colour, before label.

function bossTreant(g, ps, f, heat) {
  const P = GW_BARK, L = GW_LEAF;
  const dy = ps.dy, lx = ps.lx;
  // two trunk legs
  g.r(28 + lx - 1, FY - 26 - 2, 12, 28 - (ps.fall ? 6 : 0), P.o);
  g.r(28 + lx, FY - 26, 10, 25 - (ps.fall ? 6 : 0), P.m);
  g.r(28 + lx, FY - 26, 2, 25, P.l);
  g.r(52 + lx - 1, FY - 24 - 2, 13, 26 - (ps.fall ? 6 : 0), P.o);
  g.r(52 + lx, FY - 24, 11, 23 - (ps.fall ? 6 : 0), P.m);
  g.taper(26 + lx, FY - 1, -1, 0, 6, 3, P);                    // root toes
  g.taper(64 + lx, FY - 1, 1, 0, 5, 3, P);
  // the trunk body
  const by = FY - 62 + dy, bx = 30 + lx;
  g.rows(bx, by, Array.from({ length: 38 }, (_, j) => {
    const w = 30 - ((j * 6 / 38) | 0) + ((j & 6) === 4 ? 1 : 0);
    return [((30 - w) >> 1), w];
  }), P);
  g.r(bx + 4, by + 3, 5, 30, P.l);
  g.r(bx + 20, by + 5, 5, 28, P.d);
  // the FACE grown into the bark
  g.r(bx + 5, by + 10, 5, 4, "#120c06");
  g.r(bx + 13, by + 10, 5, 4, "#120c06");
  g.r(bx + 6, by + 11, 2, 2, heat ? HEAT[heat] : "#eaffb0");
  g.r(bx + 14, by + 11, 2, 2, heat ? HEAT[heat] : "#eaffb0");
  g.r(bx + 7, by + 18 + ps.jaw, 8, 2 + ps.jaw, "#120c06");     // a mouth that splits the grain
  // the crown of foliage — HELD UP BY BOUGHS. It used to hover clear of the trunk like a green
  // saucer; three branches now grow out of the trunk top and into the canopy's underside.
  const sw2 = TRAIL[f & 3];
  g.taper(bx + 5, by + 3, 0, -1, 12, 3, P);
  g.taper(bx + 15, by + 2, 1, -1, 13, 3, P);
  g.taper(bx + 23, by + 4, 1, -1, 10, 2, P);
  g.rows(bx - 8 - sw2, by - 14, [
    [10, 24], [6, 32], [3, 38], [1, 42], [0, 44], [0, 44], [0, 44], [1, 42], [2, 40],
    [4, 36], [7, 30], [10, 24], [14, 16], [18, 8],
  ], L);
  g.d(bx - 4 - sw2, by - 12, 36, 5, L.l, f);
  g.d(bx + 2 - sw2, by - 5, 30, 3, L.d, f + 1);
  // the branch arm: hangs, rises on wind-up, SLAMS on strike
  const ax = ps.hit ? 12 : ps.wind ? 78 : 20;
  const ay = ps.hit ? FY - 10 : ps.wind ? by - 10 : by + 26;
  g.seg(bx + 2, by + 12, ax + 4, ay - 4, 5, P.o);
  g.seg(bx + 2, by + 12, ax + 4, ay - 4, 3, P.m);
  g.taper(ax + 4, ay - 6, -1, 1, 8, 4, P);
  g.taper(ax + 8, ay - 2, -1, 1, 5, 2, P);
  if (ps.hit) for (let k = 0; k < 4; k++) g.r(ax - 2 + k * 5, FY - 2 - (k & 1) * 2, 2, 2, P.d);  // thrown dirt
}

function bossHydra(g, ps, f, heat) {
  const P = FN_SNAP, W = FN_MIRE;
  const dy = ps.dy, lx = ps.lx;
  // the pool it never leaves
  g.d(14, FY - 2, 68, 4, FN_WISP.d, f);
  // the mound body
  const bx = 34 + lx, by = FY - 26 + dy;
  g.rows(bx, by, Array.from({ length: 24 }, (_, j) => {
    const rr = Math.min(j, 23 - j);
    const ins = rr === 0 ? 5 : rr === 1 ? 2 : rr === 2 ? 1 : 0;
    return [ins, 44 - ins * 2];
  }), P);
  g.r(bx + 5, by + 2, 20, 3, P.l);
  g.d(bx + 3, by + 16, 38, 4, W.d, f);
  // three necks, weaving on their own beats
  const neck = (rootX, amp, ph, len, hw) => {
    const sway = ps.hit ? -6 : ps.wind ? 5 : Math.round(Math.sin(0) * 0) + [0, amp, 0, -amp][(f + ph) & 3];
    const hx = rootX - len + sway + (ps.hit ? -8 : 0);
    const hy = by - 18 - ((len - 14) >> 1) + (ps.hit ? 10 : ps.fall ? 14 : 0);
    g.seg(rootX, by + 4, hx + 6, hy + 6, 5, P.o);
    g.seg(rootX, by + 4, hx + 6, hy + 6, 3, P.m);
    g.seg(rootX, by + 4, hx + 6, hy + 6, 1, P.l);
    // the head: a blunt wedge with the snapjaw teeth
    g.rows(hx, hy, Array.from({ length: 9 }, (_, j) => {
      const rr = Math.min(j, 8 - j);
      return [rr === 0 ? 2 : 0, hw - (rr === 0 ? 4 : 0)];
    }), P);
    const open = ps.jaw * 2;
    g.r(hx - 3, hy + 5 + open, hw - 3, 2, P.o);
    g.r(hx - 2, hy + 4, hw - 5, 2 + open, "#1c0a10");
    for (let k = 0; k < 3; k++) g.r(hx - 1 + k * 3, hy + 4, 1, 1, "#e8dcc0");
    g.orb(hx + 3, hy + 2, 2, 2, heat ? HEAT[heat] : "#ffe27a", P.o, f + ph);
    g.taper(hx + hw - 3, hy - 2, 1, -1, 4, 2, P);              // head frill
  };
  neck(bx + 10, 3, 0, 16, 13);
  neck(bx + 22, 4, 1, 22, 14);
  neck(bx + 34, 3, 2, 12, 12);
  // the tail arch
  g.taper(bx + 42, by + 4, 1, -1, 9, 4, P);
}

function bossCyclops(g, ps, f, heat) {
  const P = CR_OGRE, T = CR_GOL;
  const dy = ps.dy, lx = ps.lx;
  const cx2 = 50 + lx;
  // legs
  const leg = (x, R2) => {
    g.r(x - 1, FY - 18 - 2, 13, 20 - (ps.fall ? 5 : 0), R2.o);
    g.r(x, FY - 18 - 2, 11, 19 - (ps.fall ? 5 : 0), R2.m);
    g.r(x, FY - 18 - 2, 2, 18, R2.l);
    g.r(x - 4, FY - 2, 16, 3, R2.o);
    g.r(x - 3, FY - 2, 14, 2, R2.m);
  };
  leg(cx2 - 16, dim(P));
  leg(cx2 + 4, P);
  // the torso: a boulder of a man
  const by = FY - 58 + dy;
  g.rows(cx2 - 24, by, Array.from({ length: 40 }, (_, j) => {
    const u = j / 39;
    const w = Math.round(48 - 18 * u);
    return [Math.round((48 - w) / 2) + Math.round(lx * 0.15 * (1 - u)), w];
  }), P);
  g.r(cx2 - 20, by + 2, 16, 4, P.l);
  g.r(cx2 + 6, by + 6, 12, 26, P.d);
  g.r(cx2 - 18, by + 34, 30, 3, P.d);
  g.r(cx2 - 10, by + 20, 20, 6, CR_GOL.d);                     // the rock belt
  for (let i = 0; i < 3; i++) g.r(cx2 - 8 + i * 7, by + 21, 4, 4, CR_GOL.m);
  // the head: all EYE
  const hy = by - 14 + (ps.jaw ? 2 : 0);
  g.rows(cx2 - 12, hy, Array.from({ length: 16 }, (_, j) => {
    const rr = Math.min(j, 15 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, 22 - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  // the EYE: an almond under a heavy brow — the old rectangular white block with a square iris
  // read as a television set in a stone face
  g.r(cx2 - 12, hy + 2, 22, 3, P.d);                           // the single brow, always angry
  [[2, 5], [1, 7], [0, 9], [1, 7], [2, 5]].forEach((s, j) =>
    g.r(cx2 - 8 + s[0], hy + 5 + j, s[1], 1, j === 0 || j === 4 ? P.o : "#e8dcc2"));
  g.r(cx2 - 5, hy + 6, 3, 3, heat ? HEAT[heat] : "#3a76c8");   // the iris — depth heats it
  g.r(cx2 - 4, hy + 6, 1, 3, "#0c0a10");                       // the slit
  const open = ps.jaw * 2;
  g.r(cx2 - 8, hy + 13, 12, 1 + open, "#1c0a10");
  if (open) for (let k = 0; k < 4; k++) g.r(cx2 - 7 + k * 3, hy + 13, 1, 2, "#e8dcc0");
  // the club arm — JOINTED, like every other heavy in the bestiary
  const wx = ps.hit ? cx2 - 38 : ps.wind ? cx2 + 30 : cx2 - 30;
  const wy = ps.hit ? FY - 12 : ps.wind ? by - 14 : by + 26;
  const ex2 = ps.hit ? cx2 - 28 : ps.wind ? cx2 + 12 : cx2 - 26;
  const ey2 = ps.hit ? by + 24 : ps.wind ? by - 6 : by + 18;
  g.tube(cx2 - 20, by + 6, ex2, ey2, 8, P);                    // upper arm, thick
  g.tube(ex2, ey2, wx + 2, wy, 6, P);                          // forearm past the elbow
  g.r(ex2 - 2, ey2 - 2, 4, 4, P.d);                            // the elbow pins the joint
  g.seg(wx + 2, wy - 16, wx + 5, wy + 4, 9, T.o);
  g.seg(wx + 3, wy - 15, wx + 5, wy + 3, 7, T.m);
  g.r(wx + 2, wy - 15, 2, 4, T.l);
  g.tube(cx2 + 16, by + 8, cx2 + 22, by + 22, 6, dim(P));      // off arm, bent at rest
  g.tube(cx2 + 22, by + 22, cx2 + 19, by + 36, 5, dim(P));
  g.r(cx2 + 17, by + 35, 6, 5, dim(P).m);                      // its fist
}

function bossDragon(g, ps, f, heat) {
  const P = mr("#1a0c10", "#48141c", "#75222a", "#a03a34", "#d06a4a");   // ash-wyrm scale
  const B = mr("#241408", "#54341c", "#7e522c", "#a87944", "#d4ab6e");   // horn bone
  const dy = ps.dy, lx = ps.lx;
  // the body: a long low mass, tail off the right edge
  const bx = 30 + lx, by = FY - 30 + dy;
  g.rows(bx, by, Array.from({ length: 26 }, (_, j) => {
    const rr = Math.min(j, 25 - j);
    const ins = rr === 0 ? 5 : rr === 1 ? 2 : rr === 2 ? 1 : 0;
    return [ins, 48 - ins * 2];
  }), P);
  g.r(bx + 6, by + 2, 24, 3, P.l);
  g.r(bx + 4, by + 20, 40, 3, P.d);
  g.taper(bx + 46, by + 6, 1, 0, 14, 5, P);                    // the tail
  g.taper(bx + 58, by + 4, 1, -1, 5, 2, B);                    // tail spade
  // legs
  g.r(bx + 6, FY - 8, 8, 8, P.o); g.r(bx + 7, FY - 8, 6, 7, P.m);
  g.r(bx + 34, FY - 8, 8, 8, P.o); g.r(bx + 35, FY - 8, 6, 7, P.m);
  g.taper(bx + 4, FY - 1, -1, 0, 4, 2, B);                     // fore claws
  // the WING: one great sail over the back, half-folded, beating slow
  const wy2 = by - 22 - (f & 1) * 2 + (ps.fall ? 16 : 0);
  g.seg(bx + 14, by + 2, bx + 34, wy2, 3, P.o);
  g.seg(bx + 34, wy2, bx + 52, by - 6, 3, P.o);
  g.rows(bx + 16, wy2 + 2, Array.from({ length: by - wy2 - 4 }, (_, j) => {
    const u = j / Math.max(1, by - wy2 - 5);
    return [Math.round(u * 6), Math.round(34 - u * 12)];
  }), mr(P.o, "#2e0e14", "#531a20", "#7a2a28", "#a04a38"));
  g.seg(bx + 24, wy2 + 2, bx + 20, by, 1, P.o);                // wing fingers
  g.seg(bx + 34, wy2 + 1, bx + 32, by - 2, 1, P.o);
  // the neck and horned head, low and level like a gun
  const hx = bx - 22 - (ps.hit ? 6 : 0), hy = by - 10 + (ps.hit ? 6 : ps.wind ? -6 : 0);
  g.seg(bx + 4, by + 6, hx + 14, hy + 6, 6, P.o);
  g.seg(bx + 4, by + 6, hx + 14, hy + 6, 4, P.m);
  g.rows(hx, hy, Array.from({ length: 12 }, (_, j) => {
    const rr = Math.min(j, 11 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, 20 - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  g.taper(hx + 16, hy - 2, 1, -1, 7, 3, B);                    // swept horns
  g.taper(hx + 12, hy - 3, 1, -1, 5, 2, B);
  g.orb(hx + 5, hy + 3, 3, 2, heat ? HEAT[heat] : "#ffd23a", P.o, f);
  const open = ps.jaw * 2;
  g.r(hx - 3, hy + 8 + (open >> 1), 14, 2, P.o);               // the long jaw
  g.r(hx - 2, hy + 7, 12, 1 + open, "#1c0a10");
  for (let k = 0; k < 4; k++) g.r(hx - 1 + k * 3, hy + 7, 1, 1, "#e8dcc0");
  if (ps.hit) {                                                 // FIRE. the whole reason it is last.
    for (let i = 0; i < 16; i += 2) {
      const t = [3, 5, 2, 6, 4, 7, 3, 5][(i >> 1) % 8];
      g.r(hx - 6 - i, hy + 6 - (t >> 1), 2, t, i < 6 ? "#ffd75a" : "#ff7a1a");
      g.r(hx - 6 - i, hy + 6, 1, 1, "#fff3b0");
    }
    g.d(hx - 24, hy + 2, 6, 8, "#ff7a1a", f);
  }
  for (let i = 0; i < 5; i++) g.taper(bx + 8 + i * 8, by - 1, 0, -1, 3, 2, B);   // back ridge
}

function bossHerald(g, ps, f, heat) {
  const P = mr("#0a0812", "#1f1a30", "#37304e", "#544c72", "#7f78a4");   // the robe that ends realms
  const dy = ps.dy + [0, -2, 0, 1][f & 3], lx = ps.lx;                     // it floats
  const cx2 = 50 + lx;
  // the robe: tall, hem never touching the road
  const by = FY - 66 + dy;
  g.rows(cx2 - 16, by, Array.from({ length: 56 }, (_, j) => {
    const u = j / 55;
    const w = Math.round(14 + 20 * u * u);
    const frag = j > 44 ? ((j + f) % 4 === 0 ? -3 : 0) : 0;                 // the hem is TORN
    return [Math.round((34 - w) / 2), w + frag];
  }), P);
  g.r(cx2 - 6, by + 4, 3, 40, P.l);
  g.r(cx2 + 6, by + 8, 4, 36, P.d);
  for (let i = 0; i < 5; i++) g.r(cx2 - 12 + i * 6, FY - 3 - ((i + f) & 3), 2, 3, P.d);  // drifting shreds
  // the hood and the skull inside it
  const hy = by - 12;
  g.rows(cx2 - 11, hy, Array.from({ length: 16 }, (_, j) => {
    const rr = Math.min(j, 15 - j);
    return [rr === 0 ? 3 : rr === 1 ? 1 : 0, 20 - (rr === 0 ? 6 : rr === 1 ? 2 : 0)];
  }), P);
  g.r(cx2 - 8, hy + 4, 14, 9, "#050409");                       // the hood's void
  g.rows(cx2 - 7, hy + 5, [[1, 10], [0, 12], [0, 12], [1, 10], [2, 8]], NT_BONE);
  g.r(cx2 - 5, hy + 7, 3, 3, "#050409");
  g.r(cx2 + 1, hy + 7, 3, 3, "#050409");
  g.r(cx2 - 4, hy + 8, 1, 1, heat ? HEAT[heat] : "#8ae9f6");
  g.r(cx2 + 2, hy + 8, 1, 1, heat ? HEAT[heat] : "#8ae9f6");
  // THE SCYTHE: idle planted · wind-up drawn back over the shoulder · strike a full cross-body reap
  const sx = ps.hit ? cx2 - 40 : ps.wind ? cx2 + 26 : cx2 - 22;
  const sy = ps.hit ? by + 30 : ps.wind ? by - 18 : by - 14;
  const ex2 = ps.hit ? cx2 + 16 : ps.wind ? cx2 + 2 : cx2 - 16;
  const ey = ps.hit ? by - 2 : ps.wind ? by + 10 : FY - 2;
  g.seg(ex2 - 1, ey - 1, sx - 1, sy - 1, 3, NT_BONE.o);
  g.seg(ex2, ey, sx, sy, 1, NT_BONE.m);
  // the blade hangs off the top end, cutting DOWN-LEFT
  const bdx = ps.hit ? -1 : -1;
  for (let i = 0; i < 14; i++) {
    const w = Math.max(1, 4 - (i >> 2));
    g.r(sx + bdx * i - w, sy + (i >> 1) - (ps.hit ? 4 : 0), w + 2, 2, NT_KNT.o);
    g.r(sx + bdx * i - w + 1, sy + (i >> 1) - (ps.hit ? 4 : 0), w, 1, "#c8d8e8");
  }
  if (ps.hit) g.d(cx2 - 34, by + 8, 26, 3, "#8ae9f6", f);       // the reap line hangs in the air
  g.tube(cx2 - 8, by + 10, ex2 + 2, ey - 6, 3, P);
  // the lantern it carries for the souls
  const ch = f & 3;
  g.seg(cx2 + 10, by + 12, cx2 + 14 - ch, by + 22, 1, NT_BONE.d);
  g.r(cx2 + 12 - ch, by + 22, 5, 6, NT_KNT.o);
  g.r(cx2 + 13 - ch, by + 23, 3, 4, "#8ae9f6");
  g.r(cx2 + 14 - ch, by + 24, 1, 1, "#ffffff");
}

const BOSSES = [
  { name: "elder treant", paint: bossTreant, shadow: 60 },
  { name: "fen hydra", paint: bossHydra, shadow: 62 },
  { name: "cyclops of the pass", paint: bossCyclops, shadow: 58 },
  { name: "ash dragon", paint: bossDragon, shadow: 66 },
  { name: "the death herald", paint: bossHerald, shadow: 44 },
];

// ── the mimic ────────────────────────────────────────────────────────────────────────────
// The one creature that follows the TREASURE, not the realm — its strapping picks up the realm's trim
// colour so it still belongs to the road it ambushed you on.
const MIMIC_WOOD = mr("#221306", "#4e2f12", "#75491e", "#9c672f", "#c89250");
const MIMIC_TRIMS = [GW_MOSS, FN_MIRE, CR_GOL, AS_REV, NT_KNT];

function paintMimic(g, ps, f, heat, biome) {
  const W2 = MIMIC_WOOD, T = MIMIC_TRIMS[biome] || CR_GOL;
  const dy = ps.dy, lx = ps.lx;
  const bx = 32 + lx, by = FY - 22 + dy;
  const open = ps.hit ? 14 : ps.wind ? 10 : ps.jaw * 2 + (f === 1 ? 1 : 0);
  // the box
  g.rows(bx, by, Array.from({ length: 20 }, (_, j) => [j === 0 || j === 19 ? 1 : 0, j === 0 || j === 19 ? 30 : 32]), W2);
  for (let i = 0; i < 3; i++) g.r(bx + 4 + i * 11, by, 3, 20, T.d);         // the strapping
  g.r(bx + 4, by, 3, 2, T.l);
  g.r(bx + 15, by, 3, 2, T.l);
  g.r(bx + 2, by + 3, 28, 1, W2.l);
  // the lid, hinged at the right, yawning open to the LEFT
  const la = Math.min(open, 14);
  g.rows(bx - (la >> 1), by - 8 - la, Array.from({ length: 8 }, (_, j) => [j === 0 || j === 7 ? 1 : 0, (j === 0 || j === 7 ? 30 : 32) + (la >> 2)]), W2);
  g.r(bx - (la >> 1) + 4, by - 8 - la, 3, 8, T.d);
  g.r(bx - (la >> 1) + 15, by - 8 - la, 3, 8, T.d);
  g.r(bx - (la >> 1) + 2, by - 6 - la, 26, 1, W2.l);
  // the mouth between lid and box
  if (open > 2) {
    g.r(bx - 2, by - open + 2, 32, open - 2, "#1c0a10");
    for (let k = 0; k < 6; k++) {                                          // TEETH, both rows
      g.taper(bx + 1 + k * 5, by - open + 2, 0, 1, 4, 3, ramp("#5a4a2a", "#c8b890", "#e8dcc0", "#f8f0d8", "#ffffff"));
      g.taper(bx + 3 + k * 5, by - 1, 0, -1, 4, 3, ramp("#5a4a2a", "#c8b890", "#e8dcc0", "#f8f0d8", "#ffffff"));
    }
    g.seg(bx + 8, by - 2, bx - 6 - (ps.hit ? 6 : 0), by + 6, 3, ramp("#4a0a14", "#8e1020", "#c02034", "#e05a5a", "#ff9a8e").m);  // the tongue
    g.r(bx - 8 - (ps.hit ? 6 : 0), by + 5, 4, 4, "#c02034");
  }
  g.orb(bx + 8, by - open - 4 < by - 8 ? by - 8 - la + 3 : by - 4, 3, 2, heat ? HEAT[heat] : "#ffd23a", W2.o, f);
  // the bait: coins spilling out of the seam
  g.r(bx + 24, by + 16, 3, 2, MATERIALS[5].l);
  g.r(bx + 20, by + 18, 2, 2, MATERIALS[5].m);
  g.r(bx + 27, by + 18, 2, 2, MATERIALS[5].s);
  if (!ps.hit && !ps.wind) g.r(bx + 25, by + 17, 1, 1, "#ffffff");
}

const MIMIC_NAME = "mimic";

// ── death ────────────────────────────────────────────────────────────────────────────────
// A corpse is AUTHORED per chassis, not the standing pose tipped over: the road behind the wayfarer is
// supposed to read as littered at a glance. Every heap keeps one species signature (the wolf's ears, the
// croc's jaw, the robe's dropped staff) through the spec's own palette; the chill map does the rest.

function heap(g, S, w, h, cx2 = MCX) {
  const P = S.P;
  const x = cx2 - (w >> 1), y = FY - h + 1;
  g.rows(x, y, Array.from({ length: h }, (_, j) => {
    const u = j / Math.max(1, h - 1);
    const ww = Math.round(w * (0.55 + 0.45 * u));
    return [Math.round((w - ww) * 0.35), ww];
  }), P);
  g.r(x + 4, y + 1, (w >> 1) - 2, 2, P.l);
  g.r(x + (w >> 2), y + h - 3, (w >> 1), 2, P.d);
  for (let i = 0; i < (w / 14 | 0); i++) g.r(x + 8 + i * 12, y + 2, 2, h - 5, P.d);   // settle creases
  return { x, y, w, h };
}

function corpseOf(g, spec, plan, f) {
  const S = spec, P = S.P;
  switch (plan) {
    case "quad": {
      const a = heap(g, S, S.d.bl + 6, S.d.bh - 2);
      g.tube(a.x + 4, a.y + 3, a.x - 6, FY - 1, 3, dim(P));                 // a foreleg reaching
      g.taper(a.x + a.w - 2, a.y + 2, 1, 0, S.d.tail - 2, S.d.tw, P);       // the tail, flat and still
      // the head, cheek to the road
      g.rows(a.x - S.d.hw + 2, FY - (S.d.hh - 2), Array.from({ length: S.d.hh - 2 }, (_, j) =>
        [Math.min(j, S.d.hh - 3 - j) === 0 ? 2 : 0, S.d.hw - (Math.min(j, S.d.hh - 3 - j) === 0 ? 4 : 0)]), P);
      g.r(a.x - S.d.hw + 6, FY - (S.d.hh >> 1) - 1, 3, 1, P.o);             // the shut eye — one line
      break;
    }
    case "grot": {
      const a = heap(g, S, S.d.bw + 8, S.d.bh - 3);
      g.rows(a.x - S.d.hw + 4, FY - S.d.hh + 3, Array.from({ length: S.d.hh - 3 }, (_, j) =>
        [Math.min(j, S.d.hh - 4 - j) === 0 ? 2 : 0, S.d.hw - (Math.min(j, S.d.hh - 4 - j) === 0 ? 4 : 0)]), P);
      g.r(a.x - S.d.hw + 8, FY - (S.d.hh >> 1), 4, 1, P.o);
      g.tube(a.x + 3, a.y + 2, a.x - 4, FY - 1, 2, dim(P));                 // the little arm, palm up
      g.r(a.x - 6, FY - 2, 3, 2, P.d);
      break;
    }
    case "hulk": {
      const a = heap(g, S, S.d.sw + 4, 16);
      g.tube(a.x + 6, a.y + 4, a.x - 8, FY - 2, S.d.aw - 2, dim(P));        // the weapon arm, spent
      g.rows(a.x - S.d.hw, FY - S.d.hh + 4, Array.from({ length: S.d.hh - 4 }, (_, j) =>
        [0, S.d.hw - (j === 0 ? 3 : 0)]), P);
      break;
    }
    case "fly": {                                                            // grounded at last
      const a = heap(g, S, S.d.bw + 10, Math.max(8, S.d.bh - 2));
      g.rows(a.x + a.w - 6, a.y - 4, [[0, 9], [2, 8], [4, 6]], dim(P));      // one wing, tented over it
      g.d(a.x - 3, a.y - 3, a.w + 6, 3, P.l, f);                             // the light guttering out
      g.r(a.x + 3, a.y + 2, 2, 1, P.o);                                      // the eye, a shut line
      break;
    }
    case "robe": {                                                           // an EMPTY robe
      const a = heap(g, S, S.d.hem + 8, 9);
      g.seg(a.x - 10, FY - 3, a.x + 10, FY - 5, 1, S.T.m);                   // the dropped staff…
      g.r(a.x - 12, FY - 6, 3, 3, S.T.o);
      g.d(a.x - 11, FY - 5, 2, 2, S.glow, f);                                // …its orb going dark
      break;
    }
    case "crawl": {                                                          // on its back, knees curled
      const a = heap(g, S, S.d.bw, S.d.bh - 2);
      for (let k = 0; k < 3; k++) {
        g.seg(a.x + 5 + k * 7, a.y, a.x + 8 + k * 7, a.y - 5, 1, P.m);
        g.seg(a.x + 8 + k * 7, a.y - 5, a.x + 6 + k * 7, a.y - 8, 1, P.m);   // curled tips
      }
      break;
    }
    case "slug": {
      heap(g, S, S.d.bl + 4, Math.max(5, S.d.bh - 4));                        // deflated
      break;
    }
  }
  if (S.dead) S.dead(g, f);
}

function corpseBoss(g, biome, f, heat) {
  // a boss dies BIG: the same heap language, realm-sized, with the one prop that names it
  const B = BOSSES[biome];
  switch (biome) {
    case 0: {                                                                // the fallen trunk
      const a = heap(g, { P: GW_BARK }, 62, 16);
      g.d(a.x + 6, a.y - 6, 30, 6, GW_LEAF.d, f);                            // dead crown
      g.r(a.x + 10, a.y + 3, 5, 4, "#120c06");                               // the face, gone dark
      g.r(a.x + 20, a.y + 3, 5, 4, "#120c06");
      break;
    }
    case 1: {
      const a = heap(g, { P: FN_SNAP }, 58, 12);
      for (let k = 0; k < 3; k++) {                                          // three heads, flat
        g.rows(a.x - 10 + k * 4, FY - 7 - k * 5, [[0, 12], [1, 10]], FN_SNAP);
        g.r(a.x - 7 + k * 4, FY - 6 - k * 5, 3, 1, FN_SNAP.o);
      }
      g.d(a.x + 4, FY - 2, 50, 3, FN_WISP.d, f);
      break;
    }
    case 2: {
      const a = heap(g, { P: CR_OGRE }, 56, 18);
      g.orb(a.x + 14, a.y + 4, 8, 6, "#f4ead6", CR_OGRE.o, 0);
      g.r(a.x + 17, a.y + 6, 3, 3, "#2a2a34");                               // the eye, emptied
      g.seg(a.x + 40, a.y - 4, a.x + 52, FY - 2, 6, CR_GOL.o);               // the club across it
      g.seg(a.x + 41, a.y - 3, a.x + 51, FY - 3, 4, CR_GOL.m);
      break;
    }
    case 3: {
      const a = heap(g, { P: ramp("#1a0c10", "#48141c", "#75222a", "#a03a34", "#d06a4a") }, 64, 14);
      // the wing, a fallen tent over the body
      g.rows(a.x + 10, a.y - 12, Array.from({ length: 12 }, (_, j) => [j, Math.max(4, 40 - j * 2)]),
             ramp("#1a0c10", "#2e0e14", "#531a20", "#7a2a28", "#a04a38"));
      g.taper(a.x - 8, FY - 4, -1, 0, 8, 3, ramp("#241408", "#54341c", "#7e522c", "#a87944", "#d4ab6e"));  // the jaw line
      g.d(a.x + 6, a.y + 2, 12, 3, "#ff7a1a", f);                            // embers dying in it
      break;
    }
    case 4: {
      const a = heap(g, { P: ramp("#0a0812", "#1f1a30", "#37304e", "#544c72", "#7f78a4") }, 44, 8);
      g.rows(a.x + 8, FY - 9, [[1, 10], [0, 12], [0, 12], [1, 10], [2, 8]], NT_BONE);   // the skull remains
      g.r(a.x + 11, FY - 7, 2, 2, "#050409");
      g.r(a.x + 15, FY - 7, 2, 2, "#050409");
      g.seg(a.x - 8, FY - 12, a.x + 30, FY - 2, 1, NT_BONE.m);               // the scythe across the road
      for (let i = 0; i < 10; i++) g.r(a.x - 10 - (i >> 1), FY - 12 + (i >> 1), 3, 2, NT_KNT.o);
      break;
    }
  }
}

function corpseMimic(g, biome, f) {
  const W2 = MIMIC_WOOD, T = MIMIC_TRIMS[biome] || CR_GOL;
  const bx = 32, by = FY - 12;
  g.rows(bx, by, Array.from({ length: 12 }, (_, j) => [0, 32]), W2);          // the box, burst
  g.r(bx + 4, by, 3, 12, T.d);
  g.r(bx + 15, by, 3, 12, T.d);
  g.rows(bx - 14, FY - 6, [[0, 14], [1, 12], [2, 9]], W2);                    // the lid, blown clear
  for (let k = 0; k < 4; k++) g.r(bx + 2 + k * 7, by - 2, 2, 3, "#e8dcc0");   // teeth in the wreck
  for (let k = 0; k < 6; k++)                                                 // the hoard, finally honest
    g.r(bx + 6 + ((k * 7) % 24), by - 4 - (k % 3) * 2, 2, 2, k & 1 ? MATERIALS[5].m : MATERIALS[5].l);
  g.r(bx + 12, by - 6, 1, 1, "#ffffff");
}

// ── the public monster draw ──────────────────────────────────────────────────────────────
export const SPECIES_NAMES = SPECIES.map((b) => b.map((fam2) => fam2.map((s) => s.name)));
export const BOSS_NAMES = BOSSES.map((b) => b.name);
/** every creature in the game, flat — 36 names, for tests and bestiaries */
export const ALL_MONSTERS = [].concat(...SPECIES.map((b) => [].concat(...b.map((fam2) => fam2.map((s) => s.name)))),
                                      BOSS_NAMES, [MIMIC_NAME]);

/** Which species (family, rank, biome) resolves to — the renderer's one lookup, exported for tests. */
export function speciesOf(biome, family, rank) {
  const b = Math.max(0, Math.min(BIOMES - 1, biome | 0));
  if (rank >= 2) return { boss: true, biome: b, name: BOSSES[b].name };
  const s = SPECIES[b][Math.max(0, Math.min(2, family | 0))][rank ? 1 : 0];
  return { boss: false, biome: b, name: s.name };
}

/**
 * Draw one creature frame, TOP-LEFT corner at (x, y), in the shared 96×96 world box: feet on row 89,
 * shadow on 91. opts = {
 *   family 0..2 · rank 0|1|2 · level (warms the eyes) · biome 0..4 (the chain rolled it) ·
 *   mimic: true — the treasure-that-bites overrides the species lookup ·
 *   frame 0-6 (3 idle · wind-up · strike · crumple · heap) · scale · facing (-1 default, faces the hero) ·
 *   hurt · dead (forces the heap)
 * }. Same opts, same pixels.
 */
export function drawMonster(ctx, x, y, opts = {}) {
  const fam2 = Math.max(0, Math.min(2, opts.family | 0));
  const rank = Math.max(0, Math.min(2, opts.rank | 0));
  const biome = Math.max(0, Math.min(BIOMES - 1, opts.biome | 0));
  const level = Math.max(0, opts.level | 0);
  const scale = Math.max(1, opts.scale | 0 || 1);
  const facing = opts.facing === 1 ? 1 : -1;
  let f = Math.max(0, Math.min(MON_FRAMES - 1, opts.frame | 0));
  const dead = !!opts.dead || f === MON_DEATH_FRAME;
  const crumple = f === MON_CRUMPLE_FRAME && !dead;
  const heat = heatOf(level);
  const map = dead ? CHILL : crumple ? ((c) => tint(c, "#ff5a5a", 0.25)) : opts.hurt ? WOUND : null;
  ctx.imageSmoothingEnabled = false;
  const g = stylus(ctx, x, y, scale, facing === 1, MW, MH, map, null);
  const S = opts.mimic ? null : rank === 2 ? null : SPECIES[biome][fam2][rank];
  const shadowW = opts.mimic ? 38 : rank === 2 ? BOSSES[biome].shadow
    : S.plan === "fly" ? 16 : S.plan === "hulk" ? 42 : S.plan === "robe" ? 26 : 34;
  monShadow(g, shadowW, dead);
  if (dead) {
    // the road remembers: every corpse lies IN its own blood, splatter thrown past it
    bloodInto(g, "pool", 5, 91 + fam2 * 3 + biome, 8 + rank * 5, MCX - 2);
    if (opts.mimic) corpseMimic(g, biome, opts.frame | 0);
    else if (rank === 2) corpseBoss(g, biome, opts.frame | 0, heat);
    else corpseOf(g, S, S.plan, opts.frame | 0);
    bloodInto(g, "splatter", 0, 92 + fam2 + biome, 5 + rank * 3, MCX - 12);
    return { w: MW * scale, h: MH * scale };
  }
  const ps = M_POSES[Math.min(f, 5)];
  if (opts.mimic) paintMimic(g, ps, f, heat, biome);
  else if (rank === 2) BOSSES[biome].paint(g, ps, f, heat);
  else if (crumple) {
    // frame 5 is the FALL — an authored collapse per chassis, never the standing pose tinted red
    const S2 = heat ? { ...S, eye: HEAT[heat] } : S;
    FALLS[S.plan](g, S2, S.d, f);
  } else {
    const S2 = heat ? { ...S, eye: HEAT[heat] } : S;
    const a = PLANS[S.plan](g, S2, S.d, ps, f);
    a.P = S.P; a.T = S.T;
    if (S.dt) S.dt(g, { ...a, ...S.d }, ps, f, heat);
    if (heat >= 3 && !ps.fall) {                              // the deepest roads: a menace wisp
      g.r(MCX - 2, (a.hy ?? a.by ?? 40) - 8 - (f & 1), 1, 2, HEAT[3]);
      g.r(MCX + 2, (a.hy ?? a.by ?? 40) - 10 + (f & 1), 1, 2, HEAT[2]);
    }
  }
  if (crumple) {
    // the wound announces itself: an arterial burst as it goes down, and the first blood on the road
    bloodInto(g, "spurt", 3, 78 + fam2 + biome * 3, 7 + rank * 3, MCX - 6, FY - 20);
    bloodInto(g, "hit", 2, 77 + fam2 * 5 + biome, 8 + rank * 3, MCX - 8, FY - 16);
    bloodInto(g, "pool", 1, 79 + fam2, 5, MCX - 4);
  }
  return { w: MW * scale, h: MH * scale };
}

/** The full seven-frame strip for one creature — bestiary reels, offline bakes, the art test. */
export function drawMonsterSheet(ctx, x, y, opts = {}) {
  const scale = Math.max(1, opts.scale | 0 || 1);
  for (let f = 0; f < MON_FRAMES; f++)
    drawMonster(ctx, x + f * MW * scale, y, { ...opts, frame: f, scale });
  return { w: MON_FRAMES * MW * scale, h: MH * scale, cells: MON_FRAMES };
}

// ══ PROPS ════════════════════════════════════════════════════════════════════════════════
// The seventeen non-combat tiles (and the fork makes eighteen kinds) as standing set-pieces in the same
// 96-box. Authored deliberately smaller than the creatures — a chest must never compete with a boss —
// and every one of them MOVES on a four-count: still props read as painted-on, and this road is alive.

const P_STONE = ramp("#16181e", "#3c4148", "#5f666e", "#868e98", "#b4bec8");
const P_WOOD  = ramp("#1c1006", "#43280f", "#66401a", "#8c5c28", "#b8863e");
const P_EMBER = ["#ff7a1a", "#ffd75a", "#ff9e2e", "#c85a10"];
const P_WATER = ramp("#0a1c2a", "#144058", "#20648a", "#3e94c0", "#7fd0ee");
const P_GOLDp = MATERIALS[5];

const PROPS = {
  hazard(g, f) { // a vent split open in the road, breathing fire — walk wide or eat it
    g.rows(24, FY - 5, [[2, 44], [0, 48], [1, 46], [4, 40]], P_STONE);
    g.r(30, FY - 4, 36, 3, "#1c0a08");                          // the crack's dark
    for (let i = 0; i < 36; i += 3) {                           // fire teeth out of the crack
      const t = [4, 8, 2, 10, 6, 3, 9, 5, 7, 2, 8, 4][((i / 3) | 0 + f) % 12];
      const c = P_EMBER[(i + f) & 3];
      g.r(31 + i, FY - 4 - t, 2, t, c);
      g.r(31 + i, FY - 4 - t, 1, 2, "#fff3b0");
    }
    g.taper(26, FY - 5, -1, -1, 5, 3, P_STONE);                 // heat-shattered slabs
    g.taper(70, FY - 5, 1, -1, 6, 3, P_STONE);
    g.d(34, FY - 22 - (f & 1) * 2, 28, 4, "#3c3128", f);        // the smoke lid
  },
  snare(g, f) { // the reeve's iron jaws, staked and waiting
    g.rows(30, FY - 3, [[1, 34], [0, 36]], P_STONE);            // trodden base plate
    for (let k = 0; k < 5; k++) {                               // two rows of teeth, sprung open
      g.taper(33 + k * 7, FY - 4, 0, -1, 7, 3, AS_REV);
      g.taper(36 + k * 7, FY - 4, 0, -1, 5, 2, dim(AS_REV));
    }
    const gl = (f & 3) * 8;                                     // one glint runs the tooth line
    g.r(34 + gl, FY - 10, 1, 2, "#f2fbff");
    g.seg(64, FY - 3, 76, FY - 12, 1, AS_REV.d);                // the chain to the stake
    g.r(75, FY - 16, 4, 6, P_WOOD.o);
    g.r(76, FY - 15, 2, 4, P_WOOD.m);
  },
  quag(g, f) { // the bog that eats boots
    g.rows(20, FY - 6, [[4, 44], [1, 51], [0, 54], [2, 50], [6, 42]], ramp("#100e08", "#2b2414", "#453a1e", "#5f5128", "#847142"));
    g.r(28, FY - 4, 36, 2, "#1c1808");
    const bub = [[30, 0], [48, 1], [60, 2], [40, 3]];           // bubbles rise and POP on their beat
    for (const [bx, ph] of bub) {
      const k = (f + ph) & 3;
      if (k < 2) g.r(bx, FY - 5 - k, 2 + k, 2, "#5f5128");
      else if (k === 2) { g.r(bx - 1, FY - 7, 4, 3, "#847142"); g.r(bx, FY - 6, 2, 1, "#1c1808"); }
    }
    for (const rx of [22, 70, 76]) {                            // reeds lean with the frames
      g.seg(rx, FY - 2, rx + [0, 1, 1, 0][f & 3], FY - 16, 1, GW_MOSS.d);
      g.taper(rx + [0, 1, 1, 0][f & 3], FY - 18, 0, -1, 3, 2, GW_MOSS);
    }
  },
  gale(g, f) { // a dust-devil parked on the road, leaves riding it
    const c = ramp("#20242e", "#3c4454", "#5a6478", "#7e88a0", "#aab4cc");
    for (let j = 0; j < 9; j++) {                               // stacked swirl bands, phase-shifted
      const w = 10 + j * 4, y = FY - 6 - j * 8;
      const off = [0, 4, -3, 2][(f + j) & 3];
      g.d(MCX - (w >> 1) + off, y, w, 3, j & 1 ? c.m : c.l, f + j);
      g.r(MCX - (w >> 1) + off + ((f * 3 + j * 5) % Math.max(1, w - 2)), y + 1, 2, 1, c.s);
    }
    const leaves = [[0, 0], [1, 5], [2, 3], [3, 7]];            // leaves orbit at four heights
    for (const [ph, r2] of leaves) {
      const k = (f + ph) & 3;
      const lx = MCX + [-14 - r2, 0, 12 + r2, 0][k];
      const ly = FY - 20 - ph * 14 + [0, -4, 0, 4][k];
      g.r(lx, ly, 3, 2, GW_LEAF.m);
      g.r(lx + 1, ly, 1, 1, GW_LEAF.l);
    }
  },
  tollgate(g, f) { // the chain across the road, and the lantern that watches you pay
    g.r(20, FY - 34, 6, 34, P_WOOD.o);                          // near post
    g.r(21, FY - 33, 4, 32, P_WOOD.m);
    g.r(21, FY - 33, 1, 32, P_WOOD.l);
    g.r(70, FY - 30, 6, 30, P_WOOD.o);                          // far post
    g.r(71, FY - 29, 4, 28, P_WOOD.m);
    for (let i = 0; i < 46; i += 4) {                           // the chain, sagging mid-span
      const sag = Math.round(6 * Math.sin((i / 46) * 3.14159));
      g.r(25 + i, FY - 26 + sag, 3, 2, AS_REV.d);
      g.r(25 + i, FY - 26 + sag, 1, 1, AS_REV.l);
    }
    const sw2 = [0, 1, 0, -1][f & 3];                           // the lantern swings
    g.seg(48, FY - 23, 48 + sw2, FY - 17, 1, AS_REV.d);
    g.r(46 + sw2, FY - 16, 6, 7, AS_REV.o);
    g.r(47 + sw2, FY - 15, 4, 5, P_EMBER[f & 3]);
    g.r(48 + sw2, FY - 14, 1, 1, "#fff3b0");
    g.r(16, FY - 40, 14, 6, P_WOOD.o);                          // the toll board
    g.r(17, FY - 39, 12, 4, P_WOOD.m);
    g.r(19, FY - 38, 8, 1, P_GOLDp.m);                          // the price, in gilt
  },
  cache(g, f) { // an honest chest — upright, latched, and leaking a little light
    g.rows(32, FY - 18, Array.from({ length: 18 }, (_, j) => [j === 0 || j === 17 ? 1 : 0, j === 0 || j === 17 ? 30 : 32]), P_WOOD);
    g.rows(30, FY - 26, [[1, 34], [0, 36], [0, 36], [1, 34]], P_WOOD);       // the lid
    g.r(33, FY - 25, 8, 2, P_WOOD.l);
    for (const sx of [37, 53]) { g.r(sx, FY - 26, 3, 26, AS_REV.d); g.r(sx, FY - 26, 1, 3, AS_REV.l); }
    const k = f & 3;                                            // the seam breathes gold
    g.r(33, FY - 19, 30, 1, k === 1 ? P_GOLDp.s : k === 2 ? P_GOLDp.l : P_GOLDp.d);
    g.r(45, FY - 16, 6, 8, AS_REV.o);                           // the lock
    g.r(46, FY - 15, 4, 5, AS_REV.m);
    g.r(47, FY - 13, 2, 2, AS_REV.o);
    if (k === 1) g.r(34, FY - 20, 2, 1, "#ffffff");             // one escaping glint
  },
  barrow(g, f) { // the mound that pays and curses — a dolmen door set INTO an earthen dome.
    // The old version hung its stone slab eight rows clear of the mound: a UFO over a hill.
    // Every stone here now touches either the dirt or another stone.
    const E5 = ramp("#0e1408", "#243418", "#3a5226", "#547238", "#7c9c56");
    g.rows(20, FY - 22, Array.from({ length: 22 }, (_, j) => {
      const u = j / 21;
      const w = Math.round(18 + 38 * u);
      return [Math.round((56 - w) / 2), w];
    }), E5);
    g.d(30, FY - 18, 38, 4, GW_MOSS.d, f);                      // old growth on the dirt
    g.d(36, FY - 21, 20, 2, E5.l, f + 1);                       // moon on the crown
    g.r(29, FY - 12, 4, 12, P_STONE.o);                         // near upright, planted
    g.r(30, FY - 11, 2, 11, P_STONE.m);
    g.r(40, FY - 12, 4, 12, P_STONE.o);                         // far upright, planted
    g.r(41, FY - 11, 2, 11, P_STONE.d);
    g.r(27, FY - 15, 19, 4, P_STONE.o);                         // the lintel RESTS on both
    g.r(28, FY - 14, 17, 2, P_STONE.m);
    g.r(28, FY - 14, 5, 1, P_STONE.l);
    g.r(33, FY - 11, 7, 11, "#05070c");                         // the dark it keeps inside
    const k = f & 3;                                            // grave-light seeps on the third beat
    if (k === 2) { g.r(35, FY - 7, 2, 4, "#8ae9f6"); g.r(36, FY - 6, 1, 1, "#d8fbff"); }
    g.rows(56, FY - 13, [[4, 8], [3, 9], [3, 9], [2, 10], [2, 10], [1, 10], [1, 10], [0, 10],
                         [0, 10], [0, 11], [0, 11], [0, 12], [0, 12]], P_STONE);   // headstone, half-toppled
    g.r(61, FY - 11, 3, 1, P_STONE.l);
    g.r(60, FY - 8, 5, 1, P_STONE.o);                           // grave-scored lines
    g.r(60, FY - 5, 4, 1, P_STONE.o);
    g.r(74, FY - 4, 4, 2, P_GOLDp.m);                           // the glint half out of the dirt
    g.r(75, FY - 4, 1, 1, k === 1 ? "#ffffff" : P_GOLDp.s);
  },
  armory(g, f) { // a dead soldier's rack, still standing its watch
    g.r(26, FY - 34, 5, 34, P_WOOD.o);
    g.r(27, FY - 33, 3, 32, P_WOOD.m);
    g.r(62, FY - 34, 5, 34, P_WOOD.o);
    g.r(63, FY - 33, 3, 32, P_WOOD.m);
    g.r(24, FY - 36, 46, 4, P_WOOD.o);
    g.r(25, FY - 35, 44, 2, P_WOOD.m);
    g.seg(36, FY - 32, 36, FY - 6, 2, AS_REV.m);                // the sword, hung
    g.r(34, FY - 30, 6, 2, AS_REV.o);
    g.r(36, FY - 8, 1, 2, AS_REV.s);
    g.seg(46, FY - 33, 46, FY - 2, 1, P_WOOD.m);                // the spear, leaned
    g.taper(46, FY - 38, 0, -1, 5, 2, AS_REV);
    g.rows(52, FY - 26, Array.from({ length: 14 }, (_, j) => [Math.min(j, 13 - j) === 0 ? 1 : 0, 10 - (Math.min(j, 13 - j) === 0 ? 2 : 0)]), AS_REV);  // the shield
    g.r(54, FY - 22, 4, 4, SCARF.m);
    const k = f & 3;                                            // a banner tatter waves off the frame
    g.rows(66, FY - 33, [[0, 6 + k], [1, 5 + k], [0, 4 + (k >> 1)], [1, 3]], SCARF);
    const gl = [36, 46, 56, 46][k];                             // one glint walks the rack
    g.r(gl, FY - 24, 1, 1, "#f2fbff");
  },
  vein(g, f) { // the lode: a boulder with a lit seam
    g.rows(28, FY - 24, Array.from({ length: 24 }, (_, j) => {
      const rr = Math.min(j, 23 - j);
      const ins = rr === 0 ? 6 : rr === 1 ? 3 : rr === 2 ? 1 : 0;
      return [ins, 40 - ins * 2];
    }), P_STONE);
    g.r(34, FY - 22, 12, 3, P_STONE.l);
    g.r(36, FY - 6, 24, 2, P_STONE.d);
    g.seg(34, FY - 16, 44, FY - 10, 2, P_GOLDp.d);              // the seam, jagged
    g.seg(44, FY - 10, 56, FY - 14, 2, P_GOLDp.d);
    g.seg(35, FY - 16, 44, FY - 11, 1, P_GOLDp.m);
    g.seg(44, FY - 11, 55, FY - 14, 1, P_GOLDp.m);
    const gx = [36, 44, 50, 44][f & 3];                         // the sparkle walks the seam
    g.r(gx, FY - 14, 2, 2, P_GOLDp.s);
    g.r(gx, FY - 14, 1, 1, "#ffffff");
    g.r(24, FY - 4, 6, 3, P_STONE.m);                           // spill stones
    g.r(68, FY - 5, 5, 3, P_STONE.m);
  },
  grove(g, f) { // the spirit ring: young trees around a light that is not the sun
    for (const [tx, th, ph] of [[26, 22, 0], [70, 20, 1], [36, 16, 2], [60, 15, 3]]) {
      const swy = [0, 1, 0, -1][(f + ph) & 3];
      g.seg(tx, FY - 1, tx + swy, FY - th, 2, GW_BARK.o);
      g.seg(tx, FY - 1, tx + swy, FY - th, 1, GW_BARK.m);
      g.rows(tx + swy - 5, FY - th - 8, [[2, 7], [0, 11], [0, 11], [1, 9], [3, 5]], GW_LEAF);
      g.r(tx + swy - 3, FY - th - 7, 4, 2, GW_LEAF.l);
    }
    const k = f & 3;                                            // motes rise in the middle
    g.r(46, FY - 8 - k * 4, 2, 2, "#b6ff6a");
    g.r(52, FY - 14 - ((k + 2) & 3) * 4, 1, 2, "#eaffb0");
    g.r(43, FY - 20 - ((k + 1) & 3) * 3, 1, 1, "#ffffff");
    g.d(38, FY - 3, 22, 3, GW_LEAF.d, f);                       // the ring floor
  },
  shrine(g, f) { // a wayside saint: hooded stone, head bowed over three votive candles
    g.rows(30, FY - 6, [[1, 34], [0, 36], [2, 32]], P_STONE);          // the worn plinth
    g.rows(40, FY - 36, [                                              // the figure, hood to hem
      [4, 8], [2, 12], [1, 14], [1, 14], [2, 12], [2, 12], [2, 12], [2, 13],
      [1, 14], [1, 14], [1, 15], [1, 15], [1, 16], [1, 16], [1, 16], [1, 16],
      [0, 17], [0, 17], [0, 18], [0, 18], [0, 18], [0, 18], [1, 17], [1, 17],
      [1, 16], [2, 15], [2, 15], [2, 14], [2, 14], [3, 13],
    ], P_STONE);
    g.r(45, FY - 32, 6, 4, "#0a0d12");                                 // the hood's void, bowed
    g.r(42, FY - 34, 2, 5, P_STONE.l);                                 // moonlight on the hood's edge
    g.r(44, FY - 24, 2, 14, P_STONE.d);                                // robe folds
    g.r(52, FY - 20, 2, 11, P_STONE.d);
    g.r(48, FY - 20, 3, 4, P_STONE.l);                                 // the praying hands
    g.r(48, FY - 16, 3, 1, P_STONE.o);
    for (const [cx4, hgt, ph] of [[28, 6, 0], [34, 9, 1], [63, 7, 2]]) {   // the votives
      g.r(cx4 - 1, FY - 6 - hgt, 4, hgt, "#8f8470");
      g.r(cx4 - 1, FY - 6 - hgt, 1, hgt, "#d8cfb8");
      const k = (f + ph) & 3;
      g.r(cx4, FY - 8 - hgt - (k === 1 ? 2 : 1), 2, k === 3 ? 2 : 3, P_EMBER[k]);
      g.r(cx4, FY - 7 - hgt, 1, 1, "#fff3b0");
    }
    g.r(49, FY - 42 - (f & 3) * 2, 1, 1, "#d8cfb8");                   // one slow mote of grace
  },

  well(g, f) { // the waystone spring: rope, winch, and a light down in the water
    g.rows(32, FY - 14, Array.from({ length: 14 }, (_, j) => [j === 0 || j === 13 ? 1 : 0, j === 0 || j === 13 ? 30 : 32]), P_STONE);
    g.r(34, FY - 13, 6, 2, P_STONE.l);
    g.r(36, FY - 12, 24, 3, "#0a1c2a");                         // the dark mouth
    g.r(38 + (f & 3) * 5, FY - 11, 3, 1, P_WATER.m);            // water winking far down
    g.r(34, FY - 34, 4, 20, P_WOOD.o);                          // the frame
    g.r(58, FY - 34, 4, 20, P_WOOD.o);
    g.r(32, FY - 37, 32, 4, P_WOOD.o);
    g.r(33, FY - 36, 30, 2, P_WOOD.m);
    const k = f & 3;                                            // the winch turns, the bucket rides
    g.r(46, FY - 34, 4, 3, P_WOOD.m);
    g.seg(48, FY - 31, 48, FY - 26 - k * 2, 1, NT_BONE.d);
    g.r(45, FY - 26 - k * 2, 7, 5, P_WOOD.o);
    g.r(46, FY - 25 - k * 2, 5, 3, P_WOOD.m);
    g.r(47, FY - 25 - k * 2, 2, 1, P_WATER.l);
  },
  camp(g, f) { // the cold firepit that will take you in
    for (let i = 0; i < 8; i++) {                               // the stone ring
      const a = i / 8 * 6.28318;
      g.r(48 + Math.round(14 * Math.cos(a)) - 2, FY - 3 + Math.round(3 * Math.sin(a)), 4, 3, P_STONE.m);
    }
    g.seg(42, FY - 5, 54, FY - 7, 2, P_WOOD.d);                 // charred logs
    g.seg(44, FY - 8, 52, FY - 4, 2, P_WOOD.o);
    const k = f & 3;                                            // one shy ember — the fire WANTS lighting
    g.r(47, FY - 8 - (k === 1 ? 1 : 0), 2, 2, k === 3 ? "#c85a10" : P_EMBER[k]);
    g.r(48, FY - 9, 1, 1, k === 1 ? "#fff3b0" : "#ff9e2e");
    g.seg(20, FY - 2, 34, FY - 6, 3, P_WOOD.m);                 // the sitting log
    g.r(20, FY - 6, 3, 2, P_WOOD.l);
    g.rows(60, FY - 6, [[0, 18], [1, 16], [2, 14]], WOOL);      // a bedroll someone left
    g.r(62, FY - 5, 6, 1, WOOL.l);
    g.d(46, FY - 16 - k, 6, 3, "#3c3128", f);                   // a thread of smoke
  },
  idol(g, f) { // the old god: a leaning black monolith wearing a grin
    g.rows(38, FY - 40, Array.from({ length: 40 }, (_, j) => [Math.round(j * -0.12), 18 + (j > 34 ? 2 : 0)]),
           ramp("#08060c", "#1c1626", "#332a44", "#4e4266", "#726292"));
    g.r(40, FY - 38, 3, 30, ramp("#08060c", "#1c1626", "#332a44", "#4e4266", "#726292").l);
    const k = f & 3;                                            // the eyes light in SEQUENCE — it counts you
    g.r(41, FY - 32, 4, 4, k >= 1 ? "#ff2222" : "#3a0810");
    g.r(48, FY - 33, 4, 4, k >= 2 ? "#ff2222" : "#3a0810");
    if (k >= 1) g.r(42, FY - 31, 1, 1, "#ffb0b0");
    for (let i = 0; i < 5; i++) g.r(40 + i * 3, FY - 24, 2, 2 + (i & 1), "#08060c");   // the grin
    g.rows(30, FY - 6, [[1, 32], [0, 34], [2, 30]], P_STONE);   // the plinth
    g.r(34, FY - 3, 4, 2, P_GOLDp.m);                           // old offerings
    g.r(58, FY - 3, 3, 2, P_GOLDp.d);
    if (k === 3) g.d(36, FY - 44, 22, 3, "#4e4266", f);         // a breath of something above it
  },
  pyre(g, f) { // the unlit beacon: bone and heartwood, begging for a spark
    for (const [x0, y0, x1, y1] of [[30, FY - 2, 52, FY - 22], [64, FY - 2, 44, FY - 22], [36, FY - 2, 60, FY - 18], [58, FY - 2, 36, FY - 16]])
      g.seg(x0, y0, x1, y1, 2, P_WOOD.m);
    g.seg(31, FY - 2, 52, FY - 21, 1, P_WOOD.l);
    g.taper(40, FY - 20, 0, -1, 6, 2, NT_BONE);                 // the ribs woven through it
    g.taper(54, FY - 22, 0, -1, 7, 2, NT_BONE);
    g.rows(28, FY - 3, [[1, 40], [0, 42]], P_STONE);            // the fire-table
    const k = f & 3;                                            // the heart-ember waits
    g.r(46, FY - 12, 3, 3, k === 2 ? "#ff9e2e" : "#c85a10");
    g.r(47, FY - 11, 1, 1, k === 2 ? "#fff3b0" : "#ff7a1a");
    if (k === 2) g.r(47, FY - 16, 1, 2, "#ff9e2e");             // one hopeful spark
  },
  forge(g, f) { // the wayside forge: anvil, quench barrel, coals that remember
    g.rows(30, FY - 8, [[1, 16], [0, 18], [0, 18], [1, 16]], ramp("#0c0a08", "#2a1c12", "#46301c", "#664a2a", "#8c6c40"));  // coal bed
    for (let i = 0; i < 5; i++) g.r(32 + i * 3, FY - 7 + (i & 1), 2, 2, P_EMBER[(i + f) & 3]);
    g.r(40, FY - 22, 16, 5, AS_REV.o);                          // the anvil
    g.r(41, FY - 21, 14, 3, AS_REV.m);
    g.r(41, FY - 21, 14, 1, AS_REV.l);
    g.taper(40, FY - 20, -1, 0, 6, 3, AS_REV);                  // the horn
    g.r(44, FY - 17, 8, 9, AS_REV.d);                           // the waist
    g.r(42, FY - 9, 12, 4, AS_REV.o);
    const k = f & 3;                                            // sparks HOP off the face
    if (k === 1) { g.r(50, FY - 26, 1, 2, "#ffd75a"); g.r(53, FY - 24, 1, 1, "#fff3b0"); }
    if (k === 2) { g.r(46, FY - 27, 1, 2, "#ff9e2e"); }
    g.rows(62, FY - 16, Array.from({ length: 16 }, (_, j) => [j === 0 ? 1 : 0, j === 0 ? 12 : 14]), P_WOOD);  // quench barrel
    g.r(64, FY - 15, 10, 2, P_WATER.m);
    g.r(65 + k * 2, FY - 15, 2, 1, P_WATER.s);
    g.seg(24, FY - 2, 24, FY - 28, 2, P_WOOD.m);                // the tool post
    g.r(20, FY - 26, 4, 8, AS_REV.m);                           // hung hammer
    g.r(19, FY - 27, 6, 3, AS_REV.o);
  },
  fork(g, f) { // the parting of the ways: a leaning post, two boards, and a raven that already knows
    g.tube(47, FY - 2, 44, FY - 40, 3, P_WOOD);                        // the post, tired of standing
    g.r(44, FY - 40, 2, 3, P_WOOD.l);
    // the LEFT board: weathered, pointing back the safe way
    g.rows(24, FY - 32, [[2, 20], [0, 23], [0, 23], [2, 20]], P_WOOD);
    g.taper(23, FY - 31, -1, 0, 4, 3, P_WOOD);                         // its point
    g.r(27, FY - 30, 14, 1, P_WOOD.d);                                 // the carved groove
    // the RIGHT board: lower, gilt-edged — greed marks its own road
    g.rows(50, FY - 24, [[2, 18], [0, 21], [0, 21], [2, 18]], P_WOOD);
    g.taper(71, FY - 23, 1, 0, 4, 3, P_WOOD);
    g.r(53, FY - 22, 13, 1, P_GOLDp.d);
    g.r(53, FY - 22, 4, 1, P_GOLDp.m);
    // THE RAVEN — big enough to be a bird, hunched like a verdict
    const RV = mr("#050508", "#16161e", "#26262f", "#3a3a48", "#5c5c70");
    const k = f & 3;
    g.rows(41 + (k === 1 ? 1 : 0), FY - 52, [[3, 6], [1, 9], [0, 11], [0, 11], [1, 10], [2, 8], [4, 5]], RV);
    g.rows(38, FY - 55, [[2, 5], [0, 7], [0, 7], [1, 5]], RV);         // the head, low between shoulders
    g.r(35, FY - 53, 3, 2, "#8a6a1c");                                 // the beak
    g.r(40, FY - 54, 1, 1, "#d8fbff");                                 // the eye. it is watching you.
    g.taper(51, FY - 49, 1, 1, 6, 3, RV);                              // the tail, off the post
    g.seg(44, FY - 45, 44, FY - 41, 1, RV.o);                          // a leg gripping the post top
    if (k === 2) {                                                     // one slow half-lift of the wings
      g.rows(34, FY - 58, [[2, 7], [0, 10]], RV);
      g.rows(48, FY - 58, [[0, 10], [2, 7]], RV);
    }
    // the skull at the base — someone chose wrong
    g.rows(56, FY - 6, [[1, 6], [0, 8], [0, 8], [1, 6]], mr("#181410", "#4a4238", "#7a7060", "#a89a86", "#d8ccb4"));
    g.r(58, FY - 5, 2, 2, "#0c0a16");
    g.r(61, FY - 5, 2, 2, "#0c0a16");
    g.r(57, FY - 2, 6, 1, P_STONE.d);
  },

  relic(g, f) { // a blade in the stone — the road's one promise it always keeps
    g.rows(30, FY - 12, Array.from({ length: 12 }, (_, j) => {
      const rr = Math.min(j, 11 - j);
      const ins = rr === 0 ? 4 : rr === 1 ? 2 : 0;
      return [ins, 36 - ins * 2];
    }), P_STONE);
    g.r(34, FY - 10, 10, 2, P_STONE.l);
    g.seg(47, FY - 34, 47, FY - 10, 2, MATERIALS[3].m);         // the blade, point buried
    g.seg(48, FY - 33, 48, FY - 11, 1, MATERIALS[3].s);
    g.r(43, FY - 35, 11, 3, MATERIALS[6].o);                    // the guard
    g.r(44, FY - 34, 9, 1, MATERIALS[6].m);
    g.r(46, FY - 40, 4, 5, MATERIALS[6].d);                     // the grip
    g.r(46, FY - 43, 4, 3, MATERIALS[6].o);
    g.r(47, FY - 42, 2, 1, MATERIALS[6].s);                     // the pommel star
    const k = f & 3;                                            // light spokes wheel around it
    const spokes = [[[-8, -24], [10, -18]], [[-11, -18], [9, -26]], [[-9, -12], [12, -22]], [[-12, -22], [8, -12]]][k];
    for (const [sdx, sdy] of spokes) {
      g.r(47 + sdx, FY + sdy, sdx < 0 ? 6 : 5, 1, "#dcc2ff");
      g.r(47 + sdx + (sdx < 0 ? 6 : -1), FY + sdy, 1, 1, "#ffffff");
    }
    g.r(44 + (k & 1) * 6, FY - 14, 1, 1, "#ffffff");            // dust motes in the light
  },
};

/**
 * Draw a prop, TOP-LEFT corner at (x, y), same 96-box and ground rows as the creatures.
 * opts = { kind (see PROP_KINDS), frame (loops on PROP_FRAMES), scale }. Deterministic, as everything.
 */
export function drawProp(ctx, x, y, opts = {}) {
  const kind = PROPS[opts.kind] ? opts.kind : "hazard";
  const scale = Math.max(1, opts.scale | 0 || 1);
  const f = Math.max(0, opts.frame | 0) % PROP_FRAMES;
  ctx.imageSmoothingEnabled = false;
  const g = stylus(ctx, x, y, scale, false, MW, MH, null, null);
  for (let i = 0; i < 40; i += 2) g.r(MCX - 20 + i, MGROUND + ((i & 2) ? 1 : 0), 1, 1, "#151020");
  PROPS[kind](g, f);
  return { w: MW * scale, h: MH * scale };
}

// ══ GORE ═════════════════════════════════════════════════════════════════════════════════
// Blood is animation, not decoration: a fight whose cost is invisible does not read as a fight. All of it
// is seed-folded through ihash so a given wound always bleeds the same way on every screen.

export const BLOOD_KINDS = ["hit", "spurt", "pool", "splatter", "gib", "mist"];
export const BLOOD_FRAMES = { hit: 5, spurt: 7, pool: 6, splatter: 1, gib: 8, mist: 6 };
const GORE = ramp("#2a040a", "#5e0a14", "#a01020", "#d63838", "#ff7a6a");
const GORE_DRY = ramp("#180507", "#3a1012", "#5a1a1c", "#7a2a26", "#96453a");

function bloodInto(g, kind, f, seed, amount, cx2 = MCX, cy2 = 52) {
  const n = Math.max(3, Math.min(32, (amount | 0) * 3 + 6));
  const s0 = ihash(seed | 0);
  switch (kind) {
    case "hit": {          // a burst: FAT droplets thrown out hard, streaks where they tore loose
      for (let k = 0; k < n; k++) {
        const h = ihash(s0 + k * 71);
        const vx = ((h & 15) - 7), vy = -(((h >> 4) & 7) + 2);
        const px = cx2 + Math.round(vx * (f + 1) * 0.8);
        const py = Math.min(FY, cy2 + vy * (f + 1) + f * f);
        const sz = 1 + ((h >> 8) & 1) + ((h >> 10) & 1);       // 1..3px — blood has WEIGHT now
        g.r(px, py, sz, sz, (h & 2) ? GORE.m : GORE.d);
        if (sz > 1) g.r(px, py, 1, 1, GORE.l);
      }
      for (let k = 0; k < 3; k++) {                            // tear streaks off the wound itself
        const h = ihash(s0 + 411 + k * 59);
        g.seg(cx2, cy2, cx2 + ((h & 15) - 7) * (1 + (f >> 1)), cy2 - 4 - (h >> 4 & 7) + f * 2, 1,
              k ? GORE.d : GORE.m);
      }
      if (f >= 2) for (let k = 0; k < n; k++) {                // the rain reaching the road
        const h = ihash(s0 + 977 + k * 37);
        g.r(cx2 - 16 + (h & 31), FY - ((h >> 5) & 1), 2 + (h >> 9 & 1), 1, GORE.d);
      }
      break;
    }
    case "spurt": {        // ARTERIAL: a thick rope of it, beads breaking off, raining down-left
      for (let t2 = 0; t2 <= f * 2 + 2; t2++) {                // the rope itself, 2px thick
        const px = cx2 - Math.round(t2 * 2.2);
        const py = Math.round(cy2 - t2 * 1.6 + t2 * t2 * 0.16);
        if (py > FY) break;
        g.r(px, py, 2, 2, GORE.m);
        if (!(t2 & 3)) g.r(px, py, 1, 1, GORE.l);
      }
      for (let k = 0; k < n; k++) {                            // beads flung off the rope
        const h = ihash(s0 + k * 53);
        const t2 = (f + (k & 3)) * 1.1;
        const px = cx2 - Math.round((3 + (h & 7)) * t2 * 0.8);
        const py = Math.round(cy2 - (6 + ((h >> 3) & 7)) * t2 * 0.5 + t2 * t2);
        if (py > FY) continue;
        g.r(px, py, 1 + ((h >> 7) & 1), 1 + ((h >> 6) & 1), (h & 2) ? GORE.m : GORE.l);
      }
      g.r(cx2 - 3, cy2 - 2, 5, 4, GORE.d);                     // the wound, an open dark mouth
      g.r(cx2 - 2, cy2 - 1, 3, 2, GORE.m);
      break;
    }
    case "pool": {         // the ground REMEMBERS: wide, wet, rimmed, and it dries from the edges
      const w = Math.min(58, 14 + f * 8 + (amount | 0) * 3);
      for (let j = 0; j < 5; j++) {                            // five rows of it, irregular-edged
        const notch = ((s0 >> (j * 3)) & 3) + ((j === 0 || j === 4) ? 6 : 0);
        const ww = w - notch - j * 3;
        if (ww <= 0) continue;
        const ox = ((s0 >> (j * 5)) & 3) - 1;
        g.r(cx2 - (ww >> 1) + ox, FY - 2 + j, ww, 1, j <= 1 ? GORE.d : j === 2 ? GORE.m : GORE.d);
      }
      g.r(cx2 - (w >> 2), FY, Math.max(3, w >> 2), 1, GORE.m); // the wet heart of it
      g.r(cx2 - (w >> 3), FY, Math.max(2, w >> 3), 1, GORE.l); // gloss — still fresh enough to shine
      for (let k = 0; k < 4; k++) {                            // fingers running along the ruts
        const h = ihash(s0 + 555 + k * 43);
        g.r(cx2 - (w >> 1) - 3 - (h & 3), FY - 1 + (k & 1) * 2, 3 + (h >> 4 & 3), 1, GORE.d);
      }
      if (f >= 4) { g.r(cx2 - (w >> 1) - 2, FY + 2, 3, 1, GORE_DRY.m); g.r(cx2 + (w >> 1) - 2, FY - 2, 3, 1, GORE_DRY.m); }
      break;
    }
    case "splatter": {     // what a passer-by finds later: flecks, smears, a drag mark
      for (let k = 0; k < n + 8; k++) {
        const h = ihash(s0 + k * 29);
        const px = cx2 - 24 + (h & 47), py = FY - ((h >> 6) & 3);
        g.r(px, py, 1 + ((h >> 8) & 3), 1 + ((h >> 10) & 1), (h & 4) ? GORE_DRY.m : GORE_DRY.l);
      }
      g.seg(cx2 - 12, FY - 2, cx2 + 8, FY, 2, GORE_DRY.d);     // the drag
      g.seg(cx2 - 2, FY - 1, cx2 + 14, FY - 3, 1, GORE_DRY.m);
      break;
    }
    case "gib": {          // the PIECES — meat with bone in it, and they land somewhere
      for (let k = 0; k < Math.min(8, 3 + (amount >> 1)); k++) {
        const h = ihash(s0 + k * 101);
        const vx = ((h & 15) - 7), vy = -(((h >> 4) & 3) + 4);
        const px = cx2 + Math.round(vx * (f + 1) * 0.7);
        const py = Math.min(FY - 1, cy2 + vy * (f + 1) * 0.6 + ((f * f) >> 1));
        const sz = 3 + ((h >> 9) & 3);                          // 3..6px chunks
        g.r(px - 1, py - 1, sz + 2, sz + 2, GORE.o);
        g.r(px, py, sz, sz, GORE.m);
        g.r(px, py, 2, 1, GORE.l);
        if ((h >> 11) & 1) g.r(px + 1, py + 1, 2, 1, "#cfc4a8"); // the bone in it
        if (f > 1) g.seg(px + (vx > 0 ? -3 : 3), py - 3, px, py, 1, GORE.d);   // its trail
        if (py >= FY - 2) g.r(px - 2, FY, sz + 4, 1, GORE.d);    // the smear where it landed
      }
      if (f >= 3) bloodInto(g, "pool", f - 2, seed + 5, amount, cx2);
      break;
    }
    case "mist": {         // the red breath that hangs after a heavy blow — three layers deep now
      const rise = f * 3;
      g.d(cx2 - 12 - f, cy2 - 6 - rise, 24 + f * 2, 9, GORE.d, f);
      g.d(cx2 - 8 - f, cy2 - 10 - rise, 18 + f * 2, 7, GORE.m, f + 1);
      g.d(cx2 - 4, cy2 - 13 - rise, 10 + f, 4, GORE.l, f);
      break;
    }
  }
}

/** Blood in the shared 96-box. opts = { kind, frame, scale, facing, seed, amount }. */
export function drawBlood(ctx, x, y, opts = {}) {
  const kind = BLOOD_KINDS.includes(opts.kind) ? opts.kind : "hit";
  const scale = Math.max(1, opts.scale | 0 || 1);
  const f = Math.max(0, Math.min((BLOOD_FRAMES[kind] || 5) - 1, opts.frame | 0));
  ctx.imageSmoothingEnabled = false;
  const g = stylus(ctx, x, y, scale, opts.facing === -1, MW, MH, null, null);
  bloodInto(g, kind, f, opts.seed | 0, opts.amount == null ? 5 : opts.amount | 0);
  return { w: MW * scale, h: MH * scale };
}

// ══ FATALITIES ═══════════════════════════════════════════════════════════════════════════
// The march ends ONE way per seed, staged in the same 96-box the killer stands in. Each finisher paints
// the wayfarer's OWN composed gear through a row band of the figure — the head that comes off is wearing
// your helm — so no death ever costs a pixel of new warrior art.

export const FATALITIES = [
  { name: "sundered", frames: 8 },   // the head taken clean
  { name: "riven",    frames: 8 },   // split at the waist
  { name: "spitted",  frames: 8 },   // lifted on a spear
  { name: "ashen",    frames: 9 },   // burnt standing
  { name: "rent",     frames: 8 },   // pulled apart
  { name: "buried",   frames: 8 },   // the rock wins
];

const FAT_DX = 16, FAT_DY = 29;      // the 64-cell in the 96-box: warrior ground row 60 lands on FY 89

/** one body part: the composed warrior, band-clipped, shifted, optionally recoloured — and CAGED in the
 *  96-box, so a part thrown clear still lands inside the frame it was thrown in */
function fatPart(ctx, x, y, scale, gear, ps, f, dx, dy, band, map) {
  const ox = FAT_DX + dx, oy = FAT_DY + dy;
  // caged sideways by the box, and DOWNWARD by the road itself: a thrown part stops on the ground line,
  // never in the shadow band under it
  const g = stylus(ctx, x + ox * scale, y + oy * scale, scale, false,
                   Math.min(FRAME_W, MW - ox), Math.min(FRAME_H, MGROUND + 1 - oy), map, band,
                   Math.max(0, -ox), Math.max(0, -oy));
  g.fx = false;                       // no affix glitter on the dying
  paintWayfarer(g, gear, ps, f & 3);
}

const FAT_FNS = [
  function sundered(ctx, x, y, s, gear, f, g) {
    const body = W_POSES.hit;
    const lean = Math.min(10, f * 2);                        // the body leans into its fall…
    const sink = f < 4 ? 0 : (f - 3) * 7;                    // …then goes down
    fatPart(ctx, x, y, s, gear, body, f, lean >> 1, sink, { y0: 18, y1: 63 }, f >= 6 ? CHILL : null);
    // the head, arcing away behind him, helm still on — up, over, and DOWN to the dirt
    const hdx = -4 - f * 4;
    const hdy = f < 3 ? -10 - f * 5 + f * f : Math.min(44, -16 + (f - 2) * 12);
    fatPart(ctx, x, y, s, gear, body, f, hdx, hdy, HEAD_BAND, f >= 5 ? CHILL : null);
    bloodInto(g, "spurt", Math.min(6, f), 11, 8, MCX + 2 + (lean >> 1), FY - 42 + sink);
    if (f >= 3) bloodInto(g, "pool", Math.min(5, f - 3), 12, 7, MCX - 6);
  },
  function riven(ctx, x, y, s, gear, f, g) {
    const legsSink = f < 3 ? 0 : Math.min(14, (f - 2) * 5);  // the legs learn the news slowly
    fatPart(ctx, x, y, s, gear, W_POSES.walk[0], f, 0, legsSink, LEGS_BAND, f >= 5 ? CHILL : null);
    const tdx = -2 - f * 3, tdy = f < 4 ? f * 5 : 20 + (f - 4) * 2;   // the top half goes first
    fatPart(ctx, x, y, s, gear, W_POSES.hit, f, tdx, Math.min(26, tdy), { y0: 0, y1: 37 },
            f >= 5 ? CHILL : null);
    bloodInto(g, "gib", Math.min(7, f), 21, 6, MCX - 2, FY - 22);
    if (f >= 2) bloodInto(g, "pool", Math.min(5, f - 2), 22, 9, MCX - 4);
  },
  function spitted(ctx, x, y, s, gear, f, g) {
    const lift = f < 3 ? f * 7 : Math.max(0, 21 - (f - 3) * 7);      // up the shaft, then sliding down
    // the spear itself, angled in from the right, planted
    g.seg(MCX + 34, FY - 2, MCX - 10, FY - 44, 2, P_WOOD.o);
    g.seg(MCX + 33, FY - 2, MCX - 10, FY - 43, 1, P_WOOD.m);
    g.taper(MCX - 12, FY - 48, -1, -1, 6, 3, AS_REV);
    fatPart(ctx, x, y, s, gear, W_POSES.hit, f, -2, -lift + (f >= 6 ? (f - 5) * 6 : 0), null,
            f >= 6 ? CHILL : null);
    bloodInto(g, "hit", Math.min(4, f), 31, 6, MCX - 2, FY - 30 + (f >= 6 ? 8 : -lift));
    if (f >= 3) bloodInto(g, "pool", Math.min(5, f - 3), 32, 8, MCX + 2);
  },
  function ashen(ctx, x, y, s, gear, f, g) {
    if (f < 6) {
      const burn = (c) => tint(c, "#120c0a", Math.min(0.85, f * 0.16));
      fatPart(ctx, x, y, s, gear, W_POSES.hit, f, 0, 0, null, burn);
      for (let i = 0; i < 30; i += 3) {                       // the fire climbing him
        const t = [3, 7, 4, 9, 5, 8, 3, 6, 4, 7][((i / 3) | 0 + f) % 10];
        g.r(MCX - 14 + i, FY - 4 - t - f, 2, t, P_EMBER[(i + f) & 3]);
        g.r(MCX - 14 + i, FY - 4 - t - f, 1, 1, "#fff3b0");
      }
      g.d(MCX - 10, FY - 52 - f * 2, 20, 5, "#3c3128", f);
    } else {                                                   // what a fire leaves
      g.rows(MCX - 16, FY - 5, [[3, 26], [0, 32], [1, 30], [4, 24]], ramp("#0c0a08", "#231d16", "#3a3128", "#544a3c", "#746856"));
      for (let k = 0; k < 5; k++) {
        const h = ihash(41 + k * 17);
        g.r(MCX - 12 + (h & 23), FY - 4 - ((h >> 5) & 1), 1, 1, P_EMBER[(k + f) & 3]);
      }
      g.d(MCX - 8, FY - 20 - (f - 6) * 4, 14, 4, "#3c3128", f);
      const wM = unpackItem(gear[0] | 0);                      // the blade survives the man
      if (wM) { g.seg(MCX + 8, FY - 3, MCX + 20, FY - 6, 1, MATERIALS[wM.mat].m); g.r(MCX + 19, FY - 6, 1, 1, MATERIALS[wM.mat].s); }
    }
  },
  function rent(ctx, x, y, s, gear, f, g) {
    const sep = Math.min(20, 3 + f * 3);                       // the two halves part company
    fatPart(ctx, x, y, s, gear, W_POSES.hit, f, -sep, f < 4 ? f * 3 : 12 + (f - 4) * 4, { y0: 0, y1: 37 },
            f >= 5 ? CHILL : null);
    fatPart(ctx, x, y, s, gear, W_POSES.walk[2], f, sep, f < 3 ? f * 2 : 6 + (f - 3) * 5, LEGS_BAND,
            f >= 5 ? CHILL : null);
    bloodInto(g, "gib", Math.min(7, f), 51, 8, MCX, FY - 26);
    bloodInto(g, "mist", Math.min(5, f), 52, 5, MCX, FY - 20);
    if (f >= 2) bloodInto(g, "pool", Math.min(5, f - 2), 53, 10, MCX);
  },
  function buried(ctx, x, y, s, gear, f, g) {
    if (f === 0) fatPart(ctx, x, y, s, gear, W_POSES.hit, f, 0, 0, null, null);
    if (f === 1) {                                             // the shadow arrives first
      fatPart(ctx, x, y, s, gear, W_POSES.hit, f, 0, 0, null, null);
      for (let i = 0; i < 28; i += 2) g.r(MCX - 14 + i, FY - 1, 1, 1, "#0a0810");
      g.rows(MCX - 14, 2, [[3, 22], [1, 26], [0, 28], [1, 26]], P_STONE);
    }
    if (f >= 2) {                                              // the rock, arrived
      const drop = Math.min(0, -40 + f * 20);
      const ry = FY - 34 + (f === 2 ? -6 : 0) + (drop < 0 ? drop : 0);
      g.rows(MCX - 17, ry, Array.from({ length: 34 }, (_, j) => {
        const rr = Math.min(j, 33 - j);
        const ins = rr === 0 ? 8 : rr === 1 ? 4 : rr === 2 ? 2 : rr === 3 ? 1 : 0;
        return [ins, 34 - ins * 2];
      }), P_STONE);
      g.r(MCX - 10, ry + 3, 12, 4, P_STONE.l);
      g.r(MCX - 2, ry + 20, 12, 8, P_STONE.d);
      // what remains visible of the wayfarer
      const bM = unpackItem(gear[2] | 0);
      g.tube(MCX - 20, FY - 4, MCX - 26, FY - 1, 3, bM ? MATERIALS[bM.mat] : WOOL);
      g.r(MCX - 29, FY - 3, 4, 3, SKIN.m);                     // the reaching hand
      g.r(MCX + 16, FY - 3, 6, 3, bM ? MATERIALS[bM.mat].d : WOOL.d);   // one boot
      if (f === 2) for (let k = 0; k < 6; k++) {               // the impact ring
        const h = ihash(61 + k * 13);
        g.r(MCX - 24 + (h & 47), FY - 5 - ((h >> 6) & 3), 2, 2, P_STONE.m);
      }
      bloodInto(g, f === 2 ? "hit" : "pool", Math.min(5, f - 2), 62, 8, MCX - 12, FY - 6);
      if (f >= 3) g.d(MCX - 20, FY - 44 + (f - 3) * 3, 40, 4, "#544a3c", f);   // settling dust
    }
  },
];

/** One fatality frame in the 96-box. opts = { which, frame, scale, facing, gear }. */
export function drawFatality(ctx, x, y, opts = {}) {
  const which = Math.max(0, Math.min(FATALITIES.length - 1, opts.which | 0));
  const scale = Math.max(1, opts.scale | 0 || 1);
  const f = Math.max(0, Math.min(FATALITIES[which].frames - 1, opts.frame | 0));
  const gear = opts.gear || NO_GEAR;
  ctx.imageSmoothingEnabled = false;
  const g = stylus(ctx, x, y, scale, opts.facing === -1, MW, MH, null, null);
  monShadow(g, 40, true);
  FAT_FNS[which](ctx, x, y, scale, gear, f, g);
  return { w: MW * scale, h: MH * scale };
}

/** Every frame of one finisher, side by side. */
export function drawFatalitySheet(ctx, x, y, opts = {}) {
  const which = Math.max(0, Math.min(FATALITIES.length - 1, opts.which | 0));
  const scale = Math.max(1, opts.scale | 0 || 1);
  const n = FATALITIES[which].frames;
  for (let f = 0; f < n; f++) drawFatality(ctx, x + f * MW * scale, y, { ...opts, frame: f, scale });
  return { w: n * MW * scale, h: MH * scale, cells: n };
}
