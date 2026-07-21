// autogame-art.js — dependency-free CANVAS pixel-art warrior, composed from the six equipment slots so the
// SILHOUETTE is the build: you should be able to see a tier-7 drop landed from across the room, without
// reading a number. Pure functions: nothing here touches game state, the DOM, storage or the network — the
// only thing that leaves this module is `ctx.fillRect` calls on the ctx you hand in.
//
// Deliberately canvas + integer rects (the pets art is SVG): sprites are blitted every frame at several
// scales, and hard pixel edges are the whole aesthetic. There is exactly one drawing primitive, `p.px()`,
// which fills an integer rect — no paths, no gradients, no anti-aliased curves anywhere.
//
// Item encoding (fixed by the contract, never re-derived here — see unpackItem below):
//   cell = 0 (empty) | 1 + tier*64 + mat*8 + affix
//   tier  0..7  quality  — drives SIZE and ornament count (stub → plume/pauldron/tower shield/longsword)
//   mat   0..7  material — drives the PALETTE only (see MATERIALS)
//   affix 0..7  affix    — drives a GLOW/particle treatment (see AFFIX_GLOW); an affix is the single most
//                          run-defining thing a player can own, so each one gets a different MOTION, not
//                          just a different colour: a colour-blind player still tells drip from flame.
// Slots are drawn back-to-front: cloak → boots → body → helm → shield → weapon.

import { unpackItem as unpackRaw } from "./autogame-engine.js";

// ── native resolution ────────────────────────────────────────────────────────────────────
// The sprites are AUTHORED on the classic coarse grid (32 warrior / 48 monster) — poses, anchors and every
// layer's coordinates live there — but they RENDER on a grid twice as fine: the pen multiplies every
// authored rect by HR, and painters lay half-authored-pixel detail on top through `p.fine()`/`p.fraw()`
// (1-px outlines on tapers, sub-pixel glints, smoother diagonals). So the exported frame constants are
// NATIVE (a monster cell is 96×96 device px at scale 1) while the painter code below keeps its authored
// coordinates — one grid for placement, one for detail, and a caller never sees the seam.
const HR = 2; // native pixels per authored pixel

const FRAME_W = 32;
const FRAME_H = 32; // square ON PURPOSE: the death pose is the standing pose rotated 90°, which is
                    // only an exact integer-rect remap (no resampling, no gaps) when W === H.
const FRAME_W_N = FRAME_W * HR, FRAME_H_N = FRAME_H * HR;
export { FRAME_W_N as FRAME_W, FRAME_H_N as FRAME_H };

export const SLOTS = ["weapon", "helm", "body", "shield", "boots", "cloak"]; // index order is contract order
export const WALK_FRAMES = 4;
export const ATTACK_FRAMES = 3;

// ── palettes ─────────────────────────────────────────────────────────────────────────────
// Four ramps per material is the minimum that still reads as a lit solid at 1x: `line` outlines the
// silhouette, `shade` is the far/underside, `base` the mass, `light` the single lit edge. Materials are
// ordered by rarity, and the hues are kept far apart (warm → cool → dark → warm → violet → green) so two
// adjacent tiers of *different* material never look like the same drop.
export const MATERIALS = [
  { base: "#b0763a", shade: "#7a4d21", light: "#e0a962", line: "#3a2410" }, // 0 bronze
  { base: "#8a8f98", shade: "#5b6068", light: "#b9bec6", line: "#2a2d33" }, // 1 iron
  { base: "#a8b8c8", shade: "#6d7d8d", light: "#dfe9f2", line: "#2c343d" }, // 2 steel
  { base: "#ccd3dc", shade: "#93a0ad", light: "#ffffff", line: "#3a4450" }, // 3 silver
  { base: "#3b3745", shade: "#221f2a", light: "#6a6480", line: "#100e15" }, // 4 obsidian
  { base: "#e0b53c", shade: "#a67a1e", light: "#fff0a0", line: "#4a3208" }, // 5 gold
  { base: "#6c5fa8", shade: "#443a70", light: "#b3a6e6", line: "#1c1730" }, // 6 meteoric
  { base: "#62a544", shade: "#3a6b2c", light: "#9fdc76", line: "#17300f" }, // 7 living
];
export const MATERIAL_NAMES = ["bronze", "iron", "steel", "silver", "obsidian", "gold", "meteoric", "living"];

// `mode` is the important field: it selects the particle BEHAVIOUR in affixAura(). Index 0 is null because
// "no affix" must be falsy at the call site — every layer does `if (A)`.
export const AFFIX_GLOW = [
  null,
  { name: "keen",     glow: "#bff6ff", spark: "#ffffff", mode: "spark"  }, // 1 hopping edge glints
  { name: "heavy",    glow: "#6a4b33", spark: "#c9b79a", mode: "weight" }, // 2 drag shadow + kicked grit
  { name: "warding",  glow: "#4fa8ff", spark: "#bfe2ff", mode: "ward"   }, // 3 dashed rune box
  { name: "swift",    glow: "#6ff0bf", spark: "#d8fff0", mode: "streak" }, // 4 speed lines behind
  { name: "vampiric", glow: "#c8102e", spark: "#ff5a6a", mode: "drip"   }, // 5 falling beads
  { name: "blazing",  glow: "#ff7a18", spark: "#ffd24a", mode: "flame"  }, // 6 flickering tongues
  { name: "hallowed", glow: "#ffe9a8", spark: "#fffce8", mode: "halo"   }, // 7 ring of light + rising motes
];

// bare-body ramps, shaped exactly like a material so the layers can treat "no item" as just another palette
const SKIN  = { base: "#d9a06a", shade: "#a97442", light: "#f0c48f", line: "#4a2c16" };
const CLOTH = { base: "#7d6a55", shade: "#544636", light: "#a08a70", line: "#2a2118" }; // undershirt/trousers
const HAIR  = { base: "#4a3423", shade: "#2c1e14", light: "#6d4d33", line: "#1a1009" };

// ── detail level ─────────────────────────────────────────────────────────────────────────
// The client used to blit these sprites at a coarse effective pixel size; it now draws finer, so painters
// may OPT IN to sub-features (strap pixels, knuckles, extra teeth) that would have read as noise before.
// `detail: 2` in any public draw's opts requests them; absent or anything else keeps the classic look.
// A module flag rather than a threaded parameter because it has to reach every layer — including the ones
// the fatalities re-enter through paintWarrior — without touching the shared layer signature. It is set at
// every public entry point, so one caller passing `detail` can never leak its choice into another's draw,
// and the same opts still always produce the same pixels.
let DETAIL = 1;
const d2 = () => DETAIL === 2;

/** 0 → null (empty slot); otherwise the packed tier/mat/affix triple.
 *
 * The arithmetic is NOT repeated here — it is delegated to the engine, which gets it from the generated
 * rules, which come from the contract. Renderers that re-derive a packing are exactly how a sprite ends up
 * showing a different item than the one the chain settled. Only the empty-slot convention differs: drawing
 * code wants a falsy "nothing here", game math wants a tier of -1 that scores 0. */
export function unpackItem(v) {
  if (!v) return null;
  return unpackRaw(v);
}

// mix two #rrggbb toward each other — used only for whole-sprite states (hurt flash, corpse fade), never
// for shading: shading comes from the authored ramps so the art stays hand-tuned.
function mix(a, b, f) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (s) => {
    const x = Math.round(((pa >> s) & 255) + (((pb >> s) & 255) - ((pa >> s) & 255)) * f);
    return (x < 16 ? "0" : "") + x.toString(16);
  };
  return "#" + ch(16) + ch(8) + ch(0);
}

// ── skeleton ─────────────────────────────────────────────────────────────────────────────
// The REDESIGNED warrior is authored directly on the 64-px NATIVE grid (that is what the grid was doubled
// for): heroic-chibi, ~2.6 head-heights, a big readable head, a broad chest, thick limbs and planted boots.
// Native rows 0-23 are the head band, 24-41 the torso band, 42-63 the legs — exactly the fatality clip
// bands (authored 0-11 / 12-20 / 21-31 × HR), so a decapitation still knows where the neck is without a
// single clip constant moving.
const CX = 15;        // authored centre column (affix boxes and the fatality scatter still read it)
const GROUND_Y = 30;  // authored ground row — the affix "weight" mode drops its grit here
const N_CX = 30;      // native centre column of the mass
const N_HEAD_Y = 8;   // crown of the bare head (helm crests get rows 0-7 of headroom)
const N_TORSO_Y = 24; // chest top; the neck seam sits at rows 22-23
const N_KNEE_Y = 50;
const N_ANKLE_Y = 56; // the boot block takes over here
const N_FOOT_Y = 59;  // last body row; the ground shadow lies on 60-61

// Poses are hand-authored, not interpolated — in NATIVE units now.
//   bob   = torso+head sink (feet stay planted, so the whole body bobs against the ground)
//   lean  = torso x shift, sells the lunge
//   footF/footB, kneeF/kneeB = x offsets from the hip for front/back leg
//   hw/hs = absolute weapon-hand / shield-hand positions
//   dir   = weapon direction, restricted to the 8 compass steps so a stepped line stays crisp
const POSES = {
  walk: [
    { bob: 0, lean: 0, kneeF:  3, footF:  7, kneeB: -2, footB: -7, hw: [44, 33], hs: [22, 35], dir: [1, -1] }, // contact
    { bob: 2, lean: 0, kneeF:  1, footF:  2, kneeB:  0, footB: -2, hw: [43, 35], hs: [23, 36], dir: [1, -1] }, // pass
    { bob: 0, lean: 0, kneeF: -2, footF: -7, kneeB:  3, footB:  7, hw: [42, 33], hs: [24, 35], dir: [1, -1] }, // contact (mirrored legs)
    { bob: 2, lean: 0, kneeF:  0, footF: -2, kneeB:  1, footB:  2, hw: [44, 35], hs: [23, 36], dir: [1, -1] }, // pass
  ],
  attack: [
    { bob: 0, lean: -2, kneeF:  2, footF:  5, kneeB: -2, footB: -6, hw: [34, 18], hs: [24, 35], dir: [-1, -1] }, // wind-up, blade back over the shoulder
    { bob: 2, lean:  4, kneeF:  6, footF: 11, kneeB: -4, footB: -8, hw: [47, 33], hs: [27, 37], dir: [ 1,  0] }, // strike: the WHOLE body lunges
    { bob: 2, lean:  2, kneeF:  4, footF:  8, kneeB: -3, footB: -7, hw: [46, 41], hs: [26, 37], dir: [ 1,  1] }, // follow-through, low
  ],
  // Drawn rotated 90° (see pen), so `dir:[1,-1]` lands on screen as down-forward: a dropped blade stuck in
  // the dirt. Limbs are splayed rather than mid-stride.
  dead: { bob: 0, lean: 0, kneeF: 5, footF: 10, kneeB: -5, footB: -10, hw: [45, 37], hs: [22, 37], dir: [1, -1] },
};

const SWAY = [0, 1, 2, 1];               // cloak / plume trail, one entry per walk frame
const FLAME = [0, 2, 3, 1, 2, 4, 1, 3];  // per-column flame heights, indexed by (column + frame) — a fixed
                                         // table instead of noise keeps every frame byte-identical

// ── the pen ──────────────────────────────────────────────────────────────────────────────
// The pen carries origin/scale/mirror/rotation/recolour so no layer can forget to apply one of them, and so
// facing and the death rotation cost exactly zero extra art. It is passed to layers as `p` in place of a raw
// ctx for that reason. Everything is clamped to the frame: sprite cells get packed side by side on sheets,
// and a stray plume or blade tip bleeding into the neighbouring cell is the classic pixel-art bug.
// `fw`/`fh` default to the warrior cell but are parameters, not constants, because the monster, prop, blood
// and fatality frames below are bigger boxes drawn with this exact same pen — one clamp, one flip, one
// recolour path for every sprite in the file.
// `clip` is an optional {y0,y1} band in AUTHORED (pre-transform) rows: it selects a BODY PART, which is how
// a fatality re-uses the warrior's own gear layers to send a head one way and a torso the other without a
// single new pixel of art.
// `bound` narrows the clamp further, in the SAME coordinates the clamp already uses. A fatality paints the
// warrior's own 32×32 layers into a 48×48 gore frame at an offset, and without this the 32-box clamp would
// happily let a flying head land outside the 48-box — the exact bleeding-into-the-next-cell bug the clamp
// exists to prevent.
function pen(ctx, ox, oy, scale, facing, rot, recolor, fw = FRAME_W, fh = FRAME_H, clip = null, bound = null) {
  const s = Math.max(1, scale | 0);
  const flip = facing < 0;
  const ROT_DY = 6;  // after rotating, drop the lying body onto the ground line instead of mid-frame
                     // (warrior-only: nothing with a non-square frame may pass rot). Authored units — the
                     // native-authored redesign reaches it through fine() as ROT_DY*HR.
  // clamp bounds in NATIVE units — put() is handed native rects, whether they came from an authored rect
  // (px/raw, ×HR) or straight from a fine stroke
  const lx = (bound ? bound.x0 : 0) * HR, ly = (bound ? bound.y0 : 0) * HR;
  const hx = (bound ? bound.x1 : fw) * HR, hy = (bound ? bound.y1 : fh) * HR;
  const put = (X, Y, W, H, col) => {
    if (X < lx) { W -= lx - X; X = lx; }
    if (Y < ly) { H -= ly - Y; Y = ly; }
    if (X + W > hx) W = hx - X;
    if (Y + H > hy) H = hy - Y;
    if (W <= 0 || H <= 0) return;
    ctx.fillStyle = recolor ? recolor(col) : col;
    ctx.fillRect(ox + X * s, oy + Y * s, W * s, H * s);
  };
  return {
    scale: s, facing, fx: !rot, // fx: corpses stop glowing — affix particles are switched off when down
    /** the one primitive: an integer rect in frame-local, facing-right, standing AUTHORED coordinates —
     *  the pen turns it into an HR×HR native block, so classic painter code renders on the fine grid */
    px(x, y, w, h, col) {
      if (!col) return;
      x |= 0; y |= 0; w |= 0; h |= 0;
      if (clip) { // trim in authored rows first, so "the head" stays the head whatever the pen does after
        if (y < clip.y0) { h -= clip.y0 - y; y = clip.y0; }
        if (y + h > clip.y1 + 1) h = clip.y1 + 1 - y;
        if (h <= 0) return;
      }
      let X = x, Y = y, W = w, H = h;
      if (rot) { X = fh - y - h; Y = x + ROT_DY; W = h; H = w; } // 90° CW, exact because W === H
      if (flip) X = fw - X - W;
      put(X * HR, Y * HR, W * HR, H * HR, col);
    },
    /** the NATIVE-grid primitive: same transforms as px, but in half-authored-pixel units — this is where
     *  the extra resolution actually lives (1-native-px outlines, sub-pixel glints, smoothed tapers) */
    fine(x, y, w, h, col) {
      if (!col) return;
      x |= 0; y |= 0; w |= 0; h |= 0;
      if (clip) { // the same authored clip bands, scaled: a fine stroke on the head is still "the head"
        const c0 = clip.y0 * HR, c1 = clip.y1 * HR + HR - 1;
        if (y < c0) { h -= c0 - y; y = c0; }
        if (y + h > c1 + 1) h = c1 + 1 - y;
        if (h <= 0) return;
      }
      let X = x, Y = y, W = w, H = h;
      if (rot) { X = fh * HR - y - h; Y = x + ROT_DY * HR; W = h; H = w; }
      if (flip) X = fw * HR - X - W;
      put(X, Y, W, H, col);
    },
    /** ground-anchored decals (contact shadow) must not tip over when the body does */
    raw(x, y, w, h, col) {
      let X = x | 0;
      if (flip) X = fw - X - (w | 0);
      put(X * HR, (y | 0) * HR, (w | 0) * HR, (h | 0) * HR, col);
    },
    /** raw's native twin: ground decals on the fine grid */
    fraw(x, y, w, h, col) {
      let X = x | 0;
      if (flip) X = fw * HR - X - (w | 0);
      put(X, y | 0, w | 0, h | 0, col);
    },
    /** checkerboard fill — our stand-in for alpha, because translucency has no place on a pixel grid */
    dither(x, y, w, h, col, phase = 0) {
      for (let j = 0; j < h; j++)
        for (let i = 0; i < w; i++)
          if (((x + i + y + j + phase) & 1) === 0) this.px(x + i, y + j, 1, 1, col);
    },
    /** stepped line: the pixel-art way to get a diagonal limb or blade with no anti-aliasing */
    limb(x0, y0, x1, y1, w, col) {
      const dx = x1 - x0, dy = y1 - y0, n = Math.max(Math.abs(dx), Math.abs(dy));
      for (let i = 0; i <= n; i++) {
        const t = n === 0 ? 0 : i / n;
        this.px(Math.round(x0 + dx * t), Math.round(y0 + dy * t), w, w, col);
      }
    },
  };
}

// shared attachment points, derived once per draw so a helm and a head can never disagree — NATIVE units
function anchors(ps) {
  const torsoX = 20 + ps.lean, torsoY = N_TORSO_Y + ps.bob;    // chest box top-left; the chest is ~20 wide
  return {
    torsoX, torsoY,
    headX: torsoX + 2 + (ps.lean >> 1), headY: N_HEAD_Y + ps.bob, // the 16-wide head sits over the chest
    shoF: [torsoX + 16, torsoY + 4],    // front (weapon) shoulder
    shoB: [torsoX + 3, torsoY + 4],     // back (shield) shoulder
    hipF: 32 + (ps.lean >> 1), hipB: 24 + (ps.lean >> 1), hipY: 42 + ps.bob,
  };
}

// ── affixes ──────────────────────────────────────────────────────────────────────────────
// One generic decorator applied by every layer to ITS OWN item box, so a blazing sword flames and a warding
// shield wards independently, and a full blazing set is unmistakable. `seed` de-phases the per-item
// animation (all six pieces flickering in lockstep looks like a bug, not an effect).
function affixAura(p, affix, box, frame, seed = 0) {
  const A = AFFIX_GLOW[affix | 0];
  if (!A || !p.fx) return;
  // Boxes arrive in authored units (the layers' contract); the PARTICLES are native now — half their old
  // size, hugging the item instead of scattering around it. Loose 2×2 blocks on a big sprite read as
  // rendering glitches, not as magic; 1-px sparks in a tight formation read as an enchantment.
  const f = frame & 3;
  const x = box.x * HR, y = box.y * HR, w = box.w * HR, h = box.h * HR;
  switch (A.mode) {
    case "spark": { // keen — a glint hops corner to corner: an edge you do not want to touch
      const pts = [[x + w - 1, y], [x, y + h - 1], [x + w - 1, y + h - 1], [x, y]];
      const [sx, sy] = pts[f];
      p.fine(sx, sy - 2, 1, 5, A.glow);
      p.fine(sx - 2, sy, 5, 1, A.glow);
      p.fine(sx, sy, 1, 1, A.spark);
      break;
    }
    case "weight": { // heavy — a hard under-shadow and grit kicked at the ground
      for (let i = 0; i < w; i += 3) p.fine(x + i + (f & 1), y + h + 1, 2, 1, A.glow);
      p.fine(x + (f & 1) * 2, GROUND_Y * HR - 2, 1, 1, A.spark);
      p.fine(x + w - 2 - (f & 1) * 2, GROUND_Y * HR - 2, 1, 1, A.spark);
      break;
    }
    case "ward": { // warding — a dashed rune box standing off the item, crawling one step per frame
      const ox = x - 3, oy = y - 3, ow = w + 6, oh = h + 6;
      for (let i = 0; i < ow; i += 2) if ((((i >> 1) + f) & 1) === 0) {
        p.fine(ox + i, oy, 1, 1, A.glow);
        p.fine(ox + ow - 1 - i, oy + oh - 1, 1, 1, A.glow);
      }
      for (let j = 0; j < oh; j += 2) if ((((j >> 1) + f) & 1) === 0) {
        p.fine(ox, oy + j, 1, 1, A.glow);
        p.fine(ox + ow - 1, oy + oh - 1 - j, 1, 1, A.glow);
      }
      p.fine(ox, oy, 1, 1, A.spark);
      p.fine(ox + ow - 1, oy + oh - 1, 1, 1, A.spark);
      break;
    }
    case "streak": { // swift — three speed lines behind the item: STRUCTURED dashes (a body and a bright
      for (let i = 0; i < 3; i++) {                    // head), never lone pixels that read as glitches
        const yy = y + 2 + i * Math.max(2, (h - 4) >> 1);
        const ln = 5 + ((f + i) & 1) * 2, sx = x - 4 - ((f + i) & 3) * 2 - ln;
        p.fine(sx, yy, ln, 2, A.glow);
        p.fine(sx + ln, yy, 1, 2, A.spark);
      }
      break;
    }
    case "drip": { // vampiric — fat beads falling off the lower edge, never past the boot line: a droplet
      for (const [bx, ph] of [[x + 2, 0], [x + w - 4, 2]]) { // is a 2×2 body with a bright cap, not a fleck
        const by = Math.min(y + h + ((f + seed + ph) & 3) * 2, GROUND_Y * HR - 5);
        p.fine(bx, by, 2, 2, A.glow);
        p.fine(bx, by, 1, 1, A.spark);
      }
      break;
    }
    case "flame": { // blazing — native-column tongues off the top edge, fixed table, no noise
      for (let i = 0; i < w; i += 2) {
        const t = FLAME[((i >> 1) + f * 3 + seed) % FLAME.length];
        if (!t) continue;
        p.fine(x + i, y - t * 2, 1, t * 2, A.glow);
        p.fine(x + i, y - t * 2, 1, 1, A.spark);
      }
      break;
    }
    case "halo": { // hallowed — a short arc of light over the piece and one rising mote
      const rw = Math.min(12, w + 4), rx = x + ((w - rw) >> 1);
      for (let i = 0; i < rw; i += 2) p.fine(rx + i + (f & 1), y - 5, 1, 1, A.glow);
      p.fine(rx + (rw >> 1), y - 7 - (f & 1), 1, 1, A.spark);
      break;
    }
  }
}

// ── native construction kit ──────────────────────────────────────────────────────────────
// The redesigned characters are SILHOUETTE-FIRST: each major mass is blocked as a filled shape with a
// continuous 1-px outline, and only then carved with big cel-shaded tone planes. These helpers work in
// NATIVE pixels through p.fine()/p.fraw(); the classic authored-grid helpers further down still serve the
// props, which keep their look.

/** far-side ramp: everything on the far side of the body is one tone step darker */
const dk = (C) => ({ base: C.shade, shade: C.line, light: C.base, line: C.line });

/** an outlined filled silhouette from row spans. spans[j] = [dx, w] (relative to x0) or null.
 *  Pass 1 stamps every row as a 3-tall line-colour block (a 1-px dilation in all four directions), pass 2
 *  fills the row itself — whatever survives of pass 1 is exactly the continuous 1-px outline. */
function blob(p, x0, y0, spans, C) {
  spans.forEach((s, j) => { if (s && s[1] > 0) p.fine(x0 + s[0] - 1, y0 + j - 1, s[1] + 2, 3, C.line); });
  spans.forEach((s, j) => { if (s && s[1] > 0) p.fine(x0 + s[0], y0 + j, s[1], 1, C.base); });
}

/** a THICK outlined limb in native px: outline pass first, mass second, then one lit ridge along the
 *  upper-left — the same three passes every mass in the redesign gets */
function limbF(p, x0, y0, x1, y1, w, C) {
  const dx = x1 - x0, dy = y1 - y0, n = Math.max(Math.abs(dx), Math.abs(dy));
  const at = (i) => { const t = n ? i / n : 0; return [Math.round(x0 + dx * t), Math.round(y0 + dy * t)]; };
  for (let i = 0; i <= n; i++) { const [X, Y] = at(i); p.fine(X - 1, Y - 1, w + 2, w + 2, C.line); }
  for (let i = 0; i <= n; i++) { const [X, Y] = at(i); p.fine(X, Y, w, w, C.base); }
  for (let i = 0; i <= n; i++) { const [X, Y] = at(i); p.fine(X, Y, 1, 1, C.light); }
}

/** native horn/ear/spike: same taper discipline as horn(), but its inputs are native px */
function hornF(p, x, y, dx, dy, n, C, w0) {
  const W0 = Math.max(2, w0 || (n >> 1));
  for (let i = 0; i < n; i++) {
    const w = Math.max(1, Math.round(W0 * (n - i) / n));
    const xx = dx < 0 ? x + dx * i - (w - 1) : x + dx * i;
    p.fine(xx - 1, y + dy * i, w + 2, 1, C.line);
    p.fine(xx, y + dy * i, w, 1, i >= n - 3 ? C.light : C.base);
  }
}

/** native eye: socket, hot iris, catchlight, pupil — big enough to have all four at last */
function eyeF(p, x, y, w, h, col, line) {
  p.fine(x - 1, y - 1, w + 2, h + 2, line);
  p.fine(x, y, w, h, col);
  if (w >= 2 && h >= 2) {
    p.fine(x, y, 1, 1, "#ffffff");
    p.fine(x + w - 1, y + h - 1, 1, Math.min(2, h - 1), line);
  }
}

// ── layers (back to front) ───────────────────────────────────────────────────────────────
// Every layer takes (p, tier, mat, affix, frame, facing) — the pose rides last so that shared signature
// stays intact. `facing` reaches the layers even though the pen has already applied it, so a layer can bias
// a detail that must NOT mirror; most never need it. `tier === null` means the slot is empty and the layer
// draws the BARE body part: the warrior is never incomplete, an empty slot is a naked slot.

function drawCloak(p, tier, mat, affix, frame, facing, ps) {
  if (tier === null) return; // the one slot whose bare version is genuinely nothing — a bare back, already
                             // covered by the body layer drawn on top of it
  const M = MATERIALS[mat], a = anchors(ps);
  const len = 20 + tier * 2;         // t0 past the belt, t7 sweeps the boot tops
  const sway = SWAY[frame % SWAY.length] * 2;
  const top = a.torsoY - 1;
  // ONE solid shaped mass hanging behind the torso: pinned at the shoulder, flaring backward (left) as it
  // falls, the bottom third swinging with the walk. Built as a blob so the outline never breaks.
  const spans = [];
  for (let i = 0; i < len; i++) {
    const t = i / Math.max(1, len - 1);
    const flare = Math.round(t * (7 + tier)) + (i > len - 7 ? sway : 0);
    let w = 7 + Math.round(t * (4 + (tier >> 1))) + (i > len - 7 ? sway : 0);
    if (tier >= 5 && i === len - 1) w -= 3;                    // tattered hem on the high tiers…
    spans.push([-flare, w]);
  }
  blob(p, a.torsoX - 2, top, spans, M);
  // cel pass: the cloak is one big plane, so it gets ONE big light and ONE big shadow
  for (let i = 2; i < len - 1; i++) {
    const [dxx, w] = spans[i];
    p.fine(a.torsoX - 2 + dxx + w - 2, top + i, 2, 1, M.shade);  // the side tucked behind the body
    if (i < len * 0.6) p.fine(a.torsoX - 2 + dxx, top + i, 2, 1, M.light); // lit trailing edge up top
  }
  p.fine(a.torsoX - 2 + spans[len - 1][0], top + len - 1, spans[len - 1][1], 1, M.shade); // hem turns under
  const [fdx] = spans[len >> 1];
  p.fine(a.torsoX - 2 + fdx + 3, top + 6, 1, len - 10, M.shade); // one long fold crease, hem to mantle
  if (tier >= 4) p.fine(a.torsoX - 2 + fdx + 6, top + 8, 1, len - 13, M.shade); // a second on the big cloaks
  if (tier >= 5) for (let k = 0; k < 4; k++)                    // …with native notches worn into it
    p.fine(a.torsoX - 2 + spans[len - 1][0] + 1 + k * 3, top + len - 1, 1, 2, M.line);
  if (tier >= 3) { // mantle: the first thing that makes a cloak read as gear and not a towel
    p.fine(a.torsoX - 4, top, 15, 4, M.line);
    p.fine(a.torsoX - 3, top + 1, 13, 2, M.base);
    p.fine(a.torsoX - 3, top + 1, 13, 1, M.light);
  }
  if (tier >= 6) { // clasp
    p.fine(a.torsoX + 9, top + 2, 3, 3, M.line);
    p.fine(a.torsoX + 10, top + 2, 2, 2, M.light);
  }
  affixAura(p, affix, { x: (a.torsoX - 14 - tier) >> 1, y: top >> 1, w: (16 + tier) >> 1, h: len >> 1 }, frame, 5);
  // ^ the aura box spans the WHOLE flare, so streaks launch from clear air and drips hang off the true hem
}

// one leg, drawn row by row: the x is lerped along hip→knee→foot so the limb bends without any curve math
// one THICK leg (native): thigh 6 px, shin 5 px, x row-lerped hip→knee→ankle so the limb bends without any
// curve math, ending in a real planted boot. Returns the ankle x so callers can hang things off it.
function drawLeg(p, hipX, hipY, kneeDx, footDx, skin, boot, bootTop) {
  const kneeX = hipX + kneeDx;
  let ax = hipX;
  for (let y = hipY; y < N_ANKLE_Y; y++) {
    const x = y <= N_KNEE_Y
      ? Math.round(hipX + kneeDx * (y - hipY) / Math.max(1, N_KNEE_Y - hipY))
      : Math.round(kneeX + (footDx - kneeDx) * (y - N_KNEE_Y) / Math.max(1, N_ANKLE_Y - N_KNEE_Y));
    const w = y < N_KNEE_Y - 2 ? 6 : 5;
    const c = boot && y >= bootTop ? boot : skin;
    p.fine(x - 1, y, w + 2, 1, c.line);
    p.fine(x, y, w, 1, c.base);
    p.fine(x, y, 2, 1, c.light);              // lit left edge — the sun sits upper-left
    p.fine(x + w - 1, y, 1, 1, c.shade);
    ax = x;
  }
  // the boot: a solid toe-forward block, PLANTED. The outline block's bottom row survives as the sole.
  const bc = boot || skin;
  const fx = ax - 1, fw = 9;
  p.fine(fx - 1, N_ANKLE_Y, fw + 2, 4, bc.line);
  p.fine(fx, N_ANKLE_Y, fw, 3, bc.base);
  p.fine(fx, N_ANKLE_Y, fw - 3, 1, bc.light);
  p.fine(fx + fw - 3, N_ANKLE_Y + 1, 3, 2, bc.light);       // the toe cap catching the light
  p.fine(fx, N_ANKLE_Y + 2, 2, 1, bc.shade);                // heel turning away
  return ax;
}

function drawBoots(p, tier, mat, affix, frame, facing, ps) {
  const M = tier === null ? null : MATERIALS[mat];
  const a = anchors(ps);
  const bootTop = tier === null ? N_ANKLE_Y : Math.max(a.hipY + 2, N_ANKLE_Y - 4 - tier * 2); // ankle→thigh
  // the far leg is one ramp step darker — the cheapest way to keep two overlapping thick legs apart
  drawLeg(p, a.hipB, a.hipY, ps.kneeB, ps.footB, dk(SKIN), M ? dk(M) : dk(CLOTH), bootTop);
  const ax = drawLeg(p, a.hipF, a.hipY, ps.kneeF, ps.footF, SKIN, M || CLOTH, bootTop);
  if (M && tier >= 4) { // knee cop — the silhouette change that says "this is armour, not a shoe"
    const kx = a.hipF + ps.kneeF;
    p.fine(kx - 2, N_KNEE_Y - 3, 9, 6, M.line);
    p.fine(kx - 1, N_KNEE_Y - 2, 7, 4, M.base);
    p.fine(kx - 1, N_KNEE_Y - 2, 7, 1, M.light);
    if (d2()) p.fine(kx + 2, N_KNEE_Y, 1, 1, M.light);      // the cop's centre rivet
  }
  if (M && tier >= 1) p.fine(ax, bootTop, 5, 1, M.light);   // the boot cuff, lit
  if (M && tier >= 6) p.fine(ax + 8, N_ANKLE_Y + 1, 2, 2, M.light);       // sabaton toe
  if (M && tier >= 7) { p.fine(ax - 4, N_ANKLE_Y + 1, 3, 1, M.light); p.fine(ax - 5, N_ANKLE_Y + 1, 1, 1, M.line); } // spur
  if (M) affixAura(p, affix, { x: (a.hipB >> 1) - 1, y: bootTop >> 1, w: 9, h: (N_FOOT_Y - bootTop) >> 1 }, frame, 3);
}

function drawBody(p, tier, mat, affix, frame, facing, ps) {
  const M = tier === null ? CLOTH : MATERIALS[mat];
  const a = anchors(ps), x = a.torsoX, y = a.torsoY;
  // Drawn AFTER the legs on purpose: the fauld/skirt of a high-tier cuirass has to fall over the thighs.
  // Silhouette first: broad shoulders → a real waist → hips under the belt, one outlined blob.
  blob(p, x, y, [
    [1, 18], [0, 20], [0, 20], [0, 20], [0, 20], [0, 20], [0, 20], [1, 18],  // rows 0-7: the chest
    [2, 16], [2, 16], [3, 14], [3, 14],                                      // 8-11: taper to the waist
    [3, 14], [3, 14],                                                        // 12-13: belt band
    [2, 15], [2, 15],                                                        // 14-15: hips
  ], M);
  // cel pass: two big planes — the upper-left chest in light, the lower-right flank in shadow
  p.fine(x + 2, y + 1, 7, 6, M.light);
  p.fine(x + 15, y + 2, 4, 8, M.shade);
  p.fine(x + 4, y + 8, 12, 1, M.shade);                       // the shadow under the chest
  p.fine(x + 8, y + 1, 4, 2, SKIN.base);                      // a sliver of neck keeps the figure human
  p.fine(x + 8, y + 2, 4, 1, SKIN.shade);
  if (tier === null) { // bare: an open-collared tunic — folds, a rope belt, big readable planes
    p.fine(x + 7, y + 3, 6, 3, SKIN.base);                    // open collar, chest showing
    p.fine(x + 12, y + 3, 1, 3, SKIN.shade);
    p.fine(x + 6, y + 3, 1, 4, CLOTH.line);                   // the collar's cut edges
    p.fine(x + 13, y + 3, 1, 4, CLOTH.line);
    p.fine(x + 5, y + 9, 1, 4, CLOTH.shade);                  // two long tunic folds, whole-height
    p.fine(x + 12, y + 9, 1, 4, CLOTH.shade);
    p.fine(x + 3, y + 12, 14, 2, CLOTH.shade);                // rope belt
    p.fine(x + 3, y + 12, 14, 1, CLOTH.light);
    if (d2()) p.fine(x + 8, y + 12, 2, 2, CLOTH.light);       // the knot
    affixAura(p, 0, { x: x >> 1, y: y >> 1, w: 10, h: 8 }, frame, 1);
    return;
  }
  if (tier >= 1) { // belt: a real strap with weight
    p.fine(x + 3, y + 12, 14, 2, M.shade);
    p.fine(x + 3, y + 13, 14, 1, M.line);
    p.fine(x + 8, y + 11, 4, 4, M.line);                      // buckle plate…
    p.fine(x + 9, y + 12, 2, 2, M.light);                     // …and its catch
  }
  if (tier >= 2) { // chest ridge: the cuirass's centre line, one clean native column
    p.fine(x + 10, y + 1, 2, 7, M.light);
    p.fine(x + 11, y + 2, 1, 6, M.base);
    if (tier < 5) { p.fine(x + 5, y + 6, 3, 1, M.shade);      // rivet shadow pair on the pecs —
                    p.fine(x + 13, y + 6, 3, 1, M.shade); }   // dropped once the plates arrive
  }
  if (tier >= 3) { // gorget closing over the neck sliver
    p.fine(x + 6, y, 8, 3, M.base);
    p.fine(x + 6, y, 8, 1, M.light);
    p.fine(x + 6, y + 2, 8, 1, M.shade);
  }
  if (tier >= 4) { // fauld: two plate rows skirting over the thighs — the torso stops being a rectangle
    p.fine(x + 1, y + 16, 18, 3, M.line);
    p.fine(x + 2, y + 16, 16, 2, M.base);
    p.fine(x + 2, y + 16, 16, 1, M.light);
    p.fine(x + 7, y + 16, 1, 2, M.line);                      // plate seams
    p.fine(x + 12, y + 16, 1, 2, M.line);
    if (d2()) { p.fine(x + 4, y + 17, 1, 1, M.light); p.fine(x + 15, y + 17, 1, 1, M.light); } // rivets
  }
  if (tier >= 6) { // tassets: a second, lower plate row on the hero who has everything
    p.fine(x + 3, y + 19, 14, 2, M.base);
    p.fine(x + 3, y + 20, 14, 1, M.shade);
  }
  if (tier >= 3) { // pauldrons, growing with tier — the width of the shoulders IS the tier read
    const pw = Math.min(10, 5 + (tier - 2));
    const px0 = a.shoF[0] - 2, py0 = a.shoF[1] - 5;
    blob(p, px0, py0, [[1, pw - 2], [0, pw], [0, pw], [0, pw], [1, pw - 2]], M);
    p.fine(px0 + 1, py0 + 1, pw - 3, 1, M.light);
    p.fine(px0 + 1, py0 + 3, pw - 2, 1, M.shade);
    if (tier >= 5) { // back pauldron too, and a spike off the front one
      blob(p, a.shoB[0] - 3, py0 + 1, [[1, pw - 3], [0, pw - 1], [0, pw - 1], [1, pw - 3]], dk(M));
      hornF(p, px0 + pw - 1, py0 - 1, 1, -1, 5, M, 3);
    }
    if (tier >= 7) { // winged pauldrons + trim: unmistakable in silhouette
      hornF(p, px0 + 2, py0 - 1, 0, -1, 6, M, 3);
      hornF(p, a.shoB[0] - 2, py0, 0, -1, 5, M, 3);
      p.fine(x + 9, y + 9, 2, 2, "#ffd7e8");                  // the heart-stone set over the sternum —
                                                              // ONE ornament where trim rows were noise
    }
  }
  affixAura(p, affix, { x: x >> 1, y: y >> 1, w: 10, h: 8 }, frame, 1);
}

function drawHelm(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), x = a.headX, y = a.headY;
  // The head is the personality budget: 16×16, skull + jaw as ONE blob, face on the marching side.
  blob(p, x, y, [
    [4, 8], [2, 12], [1, 14], [0, 16], [0, 16], [0, 16], [0, 16], [0, 16],
    [0, 16], [0, 16], [0, 16], [1, 15], [1, 14], [2, 12], [3, 10], [5, 7],
  ], SKIN);
  p.fine(x + 2, y + 3, 3, 8, SKIN.light);          // the lit back-crown plane (sun upper-left)
  p.fine(x + 5, y + 14, 8, 1, SKIN.shade);         // jaw shadow rooting the head on the neck
  if (tier === null || tier < 2) { // the FACE — visible bare and under the open helms
    p.fine(x + 9, y + 6, 5, 1, HAIR.shade);        // brow
    p.fine(x + 10, y + 7, 3, 3, "#efe6d8");        // a real eye: white…
    p.fine(x + 12, y + 7, 1, 3, SKIN.line);        // …pupil looking down the road…
    p.fine(x + 9, y + 7, 1, 3, SKIN.shade);        // …and the socket's inner shadow
    p.fine(x + 14, y + 8, 1, 2, SKIN.light);       // nose bridge
    p.fine(x + 13, y + 10, 3, 1, SKIN.shade);      // nose underside
    p.fine(x + 10, y + 12, 4, 1, SKIN.line);       // mouth, set
    p.fine(x + 10, y + 13, 3, 1, SKIN.shade);      // lower lip
    p.fine(x + 2, y + 7, 3, 4, SKIN.base);         // ear
    p.fine(x + 3, y + 8, 1, 2, SKIN.shade);
  }
  if (tier === null) { // bare head: a proper head of hair, one shaped mass with a fringe
    blob(p, x - 1, y - 2, [
      [5, 9], [3, 13], [2, 15], [1, 16], [1, 8], [1, 6], [1, 4], [1, 3],
    ], HAIR);
    p.fine(x + 2, y - 1, 6, 2, HAIR.light);        // the lit sweep
    p.fine(x + 5, y + 2, 4, 1, HAIR.shade);        // shadow inside the fringe
    p.fine(x + 1, y + 5, 2, 5, HAIR.base);         // a sideburn framing the ear
    p.fine(x + 8, y + 2, 3, 2, HAIR.base);         // one fringe tooth breaking the hairline
    p.fine(x + 8, y + 2, 1, 1, HAIR.light);
    if (d2()) p.fine(x + 12, y - 2, 1, 2, HAIR.base); // one flyaway strand at fine scales
    affixAura(p, 0, { x: x >> 1, y: y >> 1, w: 8, h: 8 }, frame, 2);
    return;
  }
  const M = MATERIALS[mat];
  if (tier < 2) { // t0-1: an open sallet — cap over the crown, the face still his
    blob(p, x - 1, y - 2, [
      [5, 9], [3, 13], [2, 15], [1, 17], [0, 18], [0, 18], [0, 18], [0, 18], [0, 5],
    ], M);
    p.fine(x + 2, y - 1, 8, 2, M.light);                     // polished crown
    p.fine(x + 13, y + 1, 3, 4, M.shade);
    p.fine(x - 1, y + 5, 18, 1, M.line);                     // brow rim
    if (tier >= 1) { p.fine(x + 13, y + 5, 3, 6, M.base); p.fine(x + 13, y + 5, 1, 6, M.light); } // nasal bar
  } else { // t2+: the closed greathelm — the whole head becomes armour with a glowing slit
    blob(p, x - 1, y - 2, [
      [5, 9], [3, 13], [2, 15], [1, 17], [0, 18], [0, 18], [0, 18], [0, 18],
      [0, 18], [0, 18], [0, 18], [0, 18], [1, 17], [2, 15], [3, 13], [4, 10],
    ], M);
    p.fine(x + 2, y - 1, 7, 3, M.light);                     // crown plane
    p.fine(x + 2, y + 2, 3, 8, M.light);                     // lit cheek plane
    p.fine(x + 12, y + 2, 4, 9, M.shade);                    // far cheek rolls away
    p.fine(x - 1, y + 5, 18, 1, M.shade);                    // brow seam
    p.fine(x + 7, y + 6, 9, 3, M.line);                      // the visor slot…
    p.fine(x + 9, y + 7, 6, 1, "#ffcf6a");                   // …and the eye-glow inside it
    p.fine(x + 9, y + 7, 1, 1, "#fff2c0");
    p.fine(x + 5, y + 11, 1, 3, M.line);                     // cheek-plate seam
    if (tier >= 3) for (let k = 0; k < 3; k++) p.fine(x + 11 + k * 2, y + 11, 1, 1, M.line); // breath holes
    if (d2()) p.fine(x + 4, y + 12, 1, 1, M.light);          // the cheek rivet
  }
  if (tier >= 4) blob(p, x + 3, y - 6, [[3, 5], [1, 9], [0, 11], [0, 12]], M); // crest ridge
  if (tier >= 5) { // horns — the first read-at-a-glance tier tell on the head
    hornF(p, x, y - 2, -1, -1, 7, M, 3);
    hornF(p, x + 15, y - 2, 1, -1, 7, M, 3);
  }
  if (tier >= 6) { // plume, swaying against the walk so the head never looks frozen
    const s = SWAY[frame % SWAY.length];
    const ph = tier >= 7 ? 8 : 6;                            // fits the rows of headroom the crest leaves
    blob(p, x + 4 - s, y - ph - 1, [
      [4, 4], [2, 7], [1, 8], [0, 9], [0, 9], [0, 8], [1, 7], [1, 6],
    ].slice(0, ph), M);
    p.fine(x + 6 - s, y - ph, 3, ph - 3, M.light);           // the plume's lit spine
    if (tier >= 7) for (let i = 0; i < 5; i++)               // tail streaming behind the march
      p.fine(x + 2 - s - i * 2, y - ph + 1 + i * 2, 3, 2, i & 1 ? M.shade : M.base);
  }
  affixAura(p, affix, { x: x >> 1, y: y >> 1, w: 8, h: 8 }, frame, 2);
}

function drawShield(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), [hx, hy] = ps.hs;
  const M = tier === null ? null : MATERIALS[mat];
  // the far arm belongs to this layer: an empty shield slot still has to show a bare arm and fist
  const arm = M && tier >= 2 ? dk(M) : dk(SKIN);
  limbF(p, a.shoB[0], a.shoB[1], hx, hy, 4, arm);
  p.fine(hx - 1, hy - 1, 6, 6, arm.line);              // the fist
  p.fine(hx, hy, 4, 4, arm.base);
  p.fine(hx, hy, 4, 1, arm.light);
  if (!M) return;
  const w = 10 + tier, h = 14 + tier * 2;              // t0 buckler … t7 tower
  const sx = hx - 3, sy = hy - (h >> 1);
  const spans = [];
  for (let j = 0; j < h; j++) {                        // rounded-corner slab
    const r = Math.min(j, h - 1 - j);
    const ins = r === 0 ? 2 : r === 1 ? 1 : 0;
    spans.push([ins, w - ins * 2]);
  }
  blob(p, sx, sy, spans, M);
  p.fine(sx + 2, sy + 1, w - 4, 2, M.light);           // cel: the top edge and the lit left rim…
  p.fine(sx + 1, sy + 2, 2, h - 5, M.light);
  p.fine(sx + w - 3, sy + 3, 2, h - 6, M.shade);       // …the far rim rolling away…
  p.fine(sx + 2, sy + h - 3, w - 4, 2, M.shade);       // …and the bottom in shadow
  if (tier >= 1) { // the DEVICE: a pale lozenge on the face — heraldry, not a plank
    const dcx = sx + (w >> 1), dcy = sy + (h >> 1) - 1;
    for (let j = -3; j <= 3; j++) {
      const dw = 7 - 2 * Math.abs(j);
      p.fine(dcx - (dw >> 1), dcy + j, dw, 1, M.light);
    }
    p.fine(dcx - 1, dcy + 1, 2, 2, M.shade);           // the lozenge's own lower facet
  } else { // t0: just a boss dome
    p.fine(sx + (w >> 1) - 2, sy + (h >> 1) - 2, 4, 4, M.light);
    p.fine(sx + (w >> 1) - 1, sy + (h >> 1) + 1, 3, 1, M.shade);
  }
  if (tier >= 3) { // reinforcing bands above and below the device
    p.fine(sx + 1, sy + 3, w - 2, 1, M.shade);
    p.fine(sx + 1, sy + h - 5, w - 2, 1, M.shade);
  }
  if (tier >= 5) { // rivets in the corners, native-sized
    p.fine(sx + 2, sy + 2, 1, 1, M.light);
    p.fine(sx + w - 3, sy + 2, 1, 1, M.light);
    p.fine(sx + 2, sy + h - 3, 1, 1, M.light);
    p.fine(sx + w - 3, sy + h - 3, 1, 1, M.light);
  }
  if (tier >= 6) hornF(p, sx + (w >> 1), sy + h, 0, 1, 5, M, 4);   // the pointed foot: it can be PLANTED
  if (tier >= 7) { // top spike + edge trim
    hornF(p, sx + (w >> 1), sy - 1, 0, -1, 5, M, 3);
    p.fine(sx, sy + 2, 1, h - 4, M.light);
  }
  affixAura(p, affix, { x: sx >> 1, y: sy >> 1, w: w >> 1, h: h >> 1 }, frame, 4);
}

function drawWeapon(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), [hx, hy] = ps.hw, [dx, dy] = ps.dir;
  const M = tier === null ? null : MATERIALS[mat];
  const arm = M && tier >= 4 ? M : SKIN;
  limbF(p, a.shoF[0], a.shoF[1], hx, hy, 4, arm);      // near arm, drawn last so it sits over the shield
  p.fine(hx - 1, hy - 1, 7, 7, arm.line);              // the fist: big, closed, outlined
  p.fine(hx, hy, 5, 5, arm.base);
  p.fine(hx, hy, 5, 1, arm.light);
  p.fine(hx + 1, hy + 2, 3, 1, arm.shade);             // knuckle crease
  if (!M) { p.fine(hx, hy + 4, 5, 1, SKIN.line); return; } // bare fist: the unarmed pose is still a pose
  // t0 knife, t7 greatsword — LENGTH is the tier read, and the blade is finally a BLADE: parallel edges,
  // a lit edge line, a fuller groove, and a taper that lands its point inside the cell.
  const cx0 = hx + 2, cy0 = hy + 2;                    // the centre of the fist
  const room = (at, d, edge) => (d > 0 ? (edge - 3 - at) / d : d < 0 ? (at - 2) / -d : 99);
  const fits = Math.floor(Math.min(room(cx0, dx, FRAME_W_N), room(cy0, dy, FRAME_H_N)));
  const len = Math.max(8, Math.min(11 + tier * 4, fits));
  const bw = tier >= 4 ? 4 : 3;
  p.fine(cx0 - dx * 3 - 2, cy0 - dy * 3 - 2, 4, 4, M.shade);     // grip behind the fist
  p.fine(cx0 - dx * 5 - 2, cy0 - dy * 5 - 2, 4, 4, M.line);      // pommel…
  p.fine(cx0 - dx * 5 - 1, cy0 - dy * 5 - 1, 2, 2, M.light);     // …with its catch
  const gl = tier < 2 ? 3 : tier < 5 ? 5 : 7;          // crossguard: perpendicular, THICK, a real cross
  for (let i = -gl; i <= gl; i++)
    p.fine(cx0 + dy * i - 1, cy0 - dx * i - 1, 3, 3, Math.abs(i) === gl ? M.line : i === 0 ? M.light : M.base);
  const wAt = (i) => (i > len - 5 ? Math.max(1, bw - (i - (len - 5))) : bw);
  for (let i = 4; i <= len; i++) {                     // outline pass first — the blade is one solid object
    const w = wAt(i);
    p.fine(cx0 + dx * i - (w >> 1) - 1, cy0 + dy * i - (w >> 1) - 1, w + 2, w + 2, M.line);
  }
  for (let i = 4; i <= len; i++) {
    const w = wAt(i);
    p.fine(cx0 + dx * i - (w >> 1), cy0 + dy * i - (w >> 1), w, w, M.base);
  }
  for (let i = 4; i <= len - 4; i++) {
    p.fine(cx0 + dx * i - (bw >> 1), cy0 + dy * i - (bw >> 1), 1, 1, M.light);  // the honed edge line
    if (tier >= 3) p.fine(cx0 + dx * i, cy0 + dy * i, 1, 1, M.shade);           // the fuller groove
  }
  p.fine(cx0 + dx * len, cy0 + dy * len, 1, 1, M.light);                        // the point itself
  const tipX = cx0 + dx * len, tipY = cy0 + dy * len;
  affixAura(p, affix, { x: (Math.min(cx0, tipX) >> 1) - 1, y: (Math.min(cy0, tipY) >> 1) - 1,
                        w: (Math.abs(tipX - cx0) >> 1) + 3, h: (Math.abs(tipY - cy0) >> 1) + 3 }, frame, 0);
}

// ── public draw ──────────────────────────────────────────────────────────────────────────
const EMPTY_GEAR = [0, 0, 0, 0, 0, 0];

/**
 * Draw one warrior frame with its top-left corner at (x, y).
 * opts = { gear:[6 ints], frame:int, scale:int, facing:1|-1, hurt:bool, dead:bool, attacking:bool }
 * Same inputs always produce the same pixels — no clocks, no randomness — so callers can cache a rendered
 * sheet by (gear, frame) and diff renders in tests.
 */
export function drawWarrior(ctx, x, y, opts = {}) {
  DETAIL = opts.detail === 2 ? 2 : 1;
  const gear = opts.gear || EMPTY_GEAR;
  const scale = Math.max(1, opts.scale | 0 || 1);
  const facing = opts.facing === -1 ? -1 : 1;
  const frame = Math.max(0, opts.frame | 0);
  const dead = !!opts.dead;
  const ps = dead ? POSES.dead
    : opts.attacking ? POSES.attack[frame % POSES.attack.length]
    : POSES.walk[frame % POSES.walk.length];
  // Whole-sprite states are a colour map, not extra art: a hurt flash pushes everything toward red, a corpse
  // toward cold grey, and every layer inherits it through the pen.
  const recolor = dead ? (c) => mix(c, "#2b2430", 0.45)
    : opts.hurt ? (c) => mix(c, "#ff5a5a", 0.55)
    : null;
  // We only fill rects, but callers routinely blit this canvas into a bigger one — smoothing there would
  // undo every hard edge, so turn it off on the context we were handed.
  ctx.imageSmoothingEnabled = false;
  const p = pen(ctx, x, y, scale, facing, dead, recolor);

  // contact shadow, dithered so it reads as translucent without touching alpha; `raw` keeps it flat on the
  // ground even when the body is rotated into the death pose
  const sw = dead ? 44 : 28, sx0 = dead ? 8 : N_CX - (sw >> 1);
  for (let i = 0; i < sw; i += 2)                            // native stipple: half-size dots on both ground
    p.fraw(sx0 + i, GROUND_Y * HR + ((i & 2) ? 1 : 0), 1, 1, "#1a1420"); // rows — soft without alpha

  paintWarrior(p, gear, ps, frame, facing);
  return { w: FRAME_W_N * scale, h: FRAME_H_N * scale };
}

/** The six slot layers, back to front, against an already-configured pen. Split out of drawWarrior so the
 *  fatalities at the bottom of this file can paint the SAME gear-composed warrior into a clipped/offset pen
 *  — a decapitated head has to keep wearing its helm, and the only way to guarantee that is to keep one
 *  painter. */
function paintWarrior(p, gear, ps, frame, facing) {
  const it = (gear || EMPTY_GEAR).map(unpackItem);
  const call = (fn, slot) => {
    const g = it[slot];
    fn(p, g ? g.tier : null, g ? g.mat : 0, g ? g.affix : 0, frame, facing, ps);
  };
  call(drawCloak, 5);   // back to front: a cloak hangs behind everything…
  call(drawBoots, 4);
  call(drawBody, 2);    // …the cuirass fauld falls over the legs…
  call(drawHelm, 1);
  call(drawShield, 3);
  call(drawWeapon, 0);  // …and the weapon arm crosses in front of the shield.
}

/**
 * Render the whole animation strip in one call: 4 walk frames, 3 attack frames, then the death pose.
 * Handy for a gear-preview widget or for baking to an offscreen canvas once and blitting cells after.
 * Returns the strip size in device pixels.
 */
export function drawWarriorSheet(ctx, x, y, opts = {}) {
  const scale = Math.max(1, opts.scale | 0 || 1);
  const cells = [];
  for (let f = 0; f < WALK_FRAMES; f++) cells.push({ frame: f });
  for (let f = 0; f < ATTACK_FRAMES; f++) cells.push({ frame: f, attacking: true });
  cells.push({ frame: 0, dead: true });
  cells.forEach((c, i) =>
    drawWarrior(ctx, x + i * FRAME_W_N * scale, y, { ...opts, ...c, scale }));
  return { w: cells.length * FRAME_W_N * scale, h: FRAME_H_N * scale, cells: cells.length };
}

// ══ MONSTERS ═════════════════════════════════════════════════════════════════════════════
// The world renderer used to draw enemies as EMOJI beside this hand-drawn warrior, which read as the hero
// swinging his sword at nothing. Monsters are built from the same machinery as everything above: the same
// pen, the same single `px` rect, the same four-stop ramps, the same dither-instead-of-alpha rule.
//
// Three axes that deliberately own different things:
//   family 0 grunt | 1 brute | 2 cannon → the SILHOUETTE. Small hunched scrapper / wide low slab / tall
//                                        thin spike. Three shapes you can tell apart at 1x before colour.
//   rank   0 normal | 1 elite | 2 boss  → the SIZE and the ornament (cap, plate, crown of horns). A boss is
//                                        roughly double the normal footprint: the chapter climax must be
//                                        unmistakable without a label.
//   level  depth-scaled int             → the PALETTE BAND plus a couple of spines/runes, and NOTHING else.
//                                        If depth reshaped the silhouette you could no longer read "brute"
//                                        before it reached you, which is the only read that matters.
//
// Everything is anchored to one frame box shared by monsters, props, blood and fatalities, so a caller
// converts ground coordinates to a top-left corner exactly once.
const MON_W = 48;         // authored box — painters below work here; the EXPORTS are native (×HR)
const MON_H = 48;
const MON_CX = 24;        // centre column
const MON_FOOT_Y = 44;    // last row the feet occupy…
const MON_GROUND_Y = 45;  // …and the row the contact shadow lies on
const PROP_W = MON_W;     // props share the box: one footX/footY conversion for the whole world layer
const PROP_H = MON_H;
const MON_W_N = MON_W * HR, MON_H_N = MON_H * HR;
const MON_CX_N = MON_CX * HR;                       // centre column of the native box
const MON_FOOT_Y_N = MON_FOOT_Y * HR + (HR - 1);    // "last row" constants keep their last-row meaning:
const MON_GROUND_Y_N = MON_GROUND_Y * HR + (HR - 1);// an authored row is HR native rows, feet end on 89
export { MON_W_N as MON_W, MON_H_N as MON_H, MON_CX_N as MON_CX,
         MON_FOOT_Y_N as MON_FOOT_Y, MON_GROUND_Y_N as MON_GROUND_Y,
         MON_W_N as PROP_W, MON_H_N as PROP_H };

// Frame convention — the renderer indexes these directly, so they are exported rather than commented.
export const MON_IDLE_FRAMES = 3;   // 0,1,2 = idle/menace cycle (loop with frame % MON_IDLE_FRAMES)
export const MON_ATTACK_FRAME = 3;  // 3     = attack (lunge + swing + maw open)
export const MON_DEATH_FRAME = 4;   // 4     = death (collapsed heap; also forced by opts.dead)
export const MON_FRAMES = 5;
export const FAMILY_NAMES = ["grunt", "brute", "cannon"];
export const MON_RANK_NAMES = ["normal", "elite", "boss"];
export const PROP_KINDS = ["hazard", "cache", "shrine", "forge", "relic", "fork", "gale", "idol"];

// ── monster palettes ─────────────────────────────────────────────────────────────────────
// Four bands per family, hand-authored rather than mixed at runtime so a deep monster is still LIT, not just
// darker. Each family sours in its own direction — grunt goes bruised, brute goes charred, cannon goes cold
// — so two families at the same depth never converge on the same colour.
//   hide = the flesh/robe mass · trim = its gear (rag, iron, bone) · eye = the one hot pixel · glow = magic
const MON_PALS = [
  [ // 0 grunt — swamp green → bruise
    { hide: { base: "#6f9440", shade: "#41602a", light: "#a2c96a", line: "#16210f" }, trim: { base: "#8a6a3c", shade: "#55401f", light: "#b18c52", line: "#1e1509" }, eye: "#ffd23a", glow: "#b6ff6a" },
    { hide: { base: "#4f8f6a", shade: "#2d5a41", light: "#82c49b", line: "#10231a" }, trim: { base: "#7a6a86", shade: "#4a3d55", light: "#a99bb8", line: "#1a1420" }, eye: "#ffae2e", glow: "#7affc0" },
    { hide: { base: "#6a6a9a", shade: "#3d3d63", light: "#9c9cd0", line: "#14142a" }, trim: { base: "#6d5a86", shade: "#42345a", light: "#9c86b8", line: "#170f22" }, eye: "#ff7a2e", glow: "#9a9aff" },
    { hide: { base: "#7d4a86", shade: "#4a2650", light: "#b57cc0", line: "#200f24" }, trim: { base: "#55506a", shade: "#332f42", light: "#7d788f", line: "#120f19" }, eye: "#ff3a3a", glow: "#ff6ae0" },
  ],
  [ // 1 brute — ruddy hide → charred
    { hide: { base: "#a4664a", shade: "#6d3f2c", light: "#cf8f6c", line: "#2a1610" }, trim: { base: "#8a8f98", shade: "#5b6068", light: "#b9bec6", line: "#2a2d33" }, eye: "#ffdf6a", glow: "#ffb46a" },
    { hide: { base: "#8f6a55", shade: "#5c412f", light: "#bb9077", line: "#241610" }, trim: { base: "#6d6a62", shade: "#45433d", light: "#9a968a", line: "#1d1c18" }, eye: "#ffb43a", glow: "#ff9a4a" },
    { hide: { base: "#7a5f66", shade: "#4a3740", light: "#a68d94", line: "#201519" }, trim: { base: "#4f4a55", shade: "#302c34", light: "#7a7382", line: "#151218" }, eye: "#ff7a3a", glow: "#ff7a3a" },
    { hide: { base: "#5e4a4a", shade: "#392c2c", light: "#8c7070", line: "#180f0f" }, trim: { base: "#3b3745", shade: "#221f2a", light: "#6a6480", line: "#100e15" }, eye: "#ff3030", glow: "#ff5020" },
  ],
  [ // 2 cannon — arcane robe + bone, cooling toward spectral
    { hide: { base: "#4a5aa8", shade: "#2c376d", light: "#7d8ce0", line: "#131735" }, trim: { base: "#d9d2b8", shade: "#a49b7c", light: "#f4f0dd", line: "#3a3423" }, eye: "#7ff0ff", glow: "#9fe8ff" },
    { hide: { base: "#5a44a0", shade: "#362766", light: "#8e78e0", line: "#171034" }, trim: { base: "#cfc8ad", shade: "#9a9276", light: "#efe9d4", line: "#35301f" }, eye: "#b58cff", glow: "#c79cff" },
    { hide: { base: "#7a2f8c", shade: "#4a1a56", light: "#b968c8", line: "#250d2c" }, trim: { base: "#c6bfa8", shade: "#918a72", light: "#e9e2ce", line: "#302b1c" }, eye: "#ff7ce0", glow: "#ff9ae8" },
    { hide: { base: "#1f3c46", shade: "#12242b", light: "#3f7180", line: "#08131a" }, trim: { base: "#eaf6ff", shade: "#a8bcc8", light: "#ffffff", line: "#2a3a44" }, eye: "#ffffff", glow: "#d8ffff" },
  ],
];
// Bands step every 5 levels: `ml` runs ~1..21 over a chapter (1 + depth/32, +2 elite, +4 boss, +1 at night),
// so four bands land roughly one per quarter of the road.
const bandOf = (level) => Math.max(0, Math.min(3, ((level | 0) / 5) | 0));

// ── monster geometry ─────────────────────────────────────────────────────────────────────
// Sizes are TABLES, not a multiplier: a scaled-up grunt is a bigger grunt, but a boss has to be a different
// drawing, and integer pixels do not survive a 1.4× anyway. Rank order is enforced by the numbers here —
// every dimension grows normal → elite → boss, which is what makes the footprint test hold.
// Rank dimension tables — NATIVE pixels. Sizes are tables, not multipliers: a boss is a different DRAWING.
const GRUNT_D = [ // small and hunched: the head is nearly half of it, and the ears are half of the head
  { bw: 20, bh: 20, hw: 22, hh: 17, leg: 14, legW: 5, ear: 10, arm: 5 },
  { bw: 24, bh: 24, hw: 26, hh: 20, leg: 17, legW: 6, ear: 13, arm: 6 },
  { bw: 34, bh: 30, hw: 34, hh: 26, leg: 22, legW: 8, ear: 17, arm: 8 },
];
const BRUTE_D = [ // a trapezoid: shoulder width → hip width is the whole personality
  { sw: 38, hip: 20, bh: 38, hw: 13, hh: 11, leg: 16, legW: 8, arm: 8, maul: 10 },
  { sw: 46, hip: 24, bh: 44, hw: 15, hh: 12, leg: 18, legW: 9, arm: 9, maul: 12 },
  { sw: 62, hip: 32, bh: 52, hw: 19, hh: 15, leg: 22, legW: 12, arm: 12, maul: 16 },
];
const CANNON_D = [ // a hovering bell of robe — no legs at all; the hem floats over its own shadow
  { bw: 14, hem: 26, robeH: 40, hw: 16, hh: 15, orb: 6 },
  { bw: 17, hem: 32, robeH: 46, hw: 19, hh: 17, orb: 7 },
  { bw: 22, hem: 44, robeH: 56, hw: 24, hh: 21, orb: 9 },
];

/** a squat monster leg (native): thick bent shin + a big splayed foot, toes toward the hero (left) */
function mLeg(p, x, top, w, C, toe) {
  const FY = MON_FOOT_Y * HR + 1;                       // last foot row (89)
  p.fine(x - 1, top - 1, w + 2, FY - 3 - top + 1, C.line);
  p.fine(x, top, w, FY - 3 - top - 1, C.base);
  p.fine(x, top, 2, FY - 3 - top - 1, C.light);
  p.fine(x + w - 1, top, 1, FY - 3 - top - 1, C.shade);
  p.fine(x - toe - 1, FY - 3, w + toe + 2, 4, C.line);  // foot block; the outline's bottom row is the sole
  p.fine(x - toe, FY - 3, w + toe, 3, C.base);
  p.fine(x - toe, FY - 3, w + toe - 2, 1, C.light);
  p.fine(x - toe - 1, FY - 1, 2, 1, C.line);            // one claw off the toe
}

// Poses are hand-picked like the warrior's, and `lean` points FORWARD, which for a monster is −x: the whole
// family is authored facing left, into the oncoming hero.
const MON_POSES = [
  { bob:  0, lean:  0, arm:  0, jaw: 0 }, // 0 idle: settled, weight down
  { bob: -1, lean:  1, arm:  1, jaw: 0 }, // 1 idle: rears back, inhales
  { bob:  1, lean: -1, arm: -1, jaw: 1 }, // 2 idle: hunches in, maw cracks open
  { bob:  1, lean: -3, arm:  4, jaw: 2 }, // 3 ATTACK: lunge, weapon out, maw wide
];

// ── monster primitives ───────────────────────────────────────────────────────────────────
const darker = (C) => ({ base: C.shade, shade: C.line, light: C.base, line: C.line }); // far-side limbs

/** row spans of a rounded mass: only the first/last `r` rows are inset, so the middle keeps its full width
 *  and the shape stays a MASS instead of a lozenge. */
function rowsOf(x, y, w, h, r) {
  const out = [];
  for (let j = 0; j < h; j++) {
    const t = Math.min(j, h - 1 - j);
    const ins = t >= r ? 0 : r - t;
    const ww = w - ins * 2;
    if (ww > 0) out.push([x + ins, y + j, ww]);
  }
  return out;
}

/** The monster equivalent of the warrior's torso block: a rounded body mass with a one-pixel `line` fringe
 *  all round. The fringe is not decoration — monsters stand on a parallax landscape, not a UI panel, and an
 *  un-outlined green blob dissolves into the treeline. (Same trick as the shield layer.) */
function mass(p, x, y, w, h, C, r = 1) {
  const rows = rowsOf(x, y, w, h, r);
  if (!rows.length) return;
  for (const [rx, ry, rw] of rows) p.px(rx - 1, ry, rw + 2, 1, C.line);
  p.px(rows[0][0], rows[0][1] - 1, rows[0][2], 1, C.line);
  const last = rows[rows.length - 1];
  p.px(last[0], last[1] + 1, last[2], 1, C.line);
  for (const [rx, ry, rw] of rows) {
    p.px(rx, ry, rw, 1, C.base);
    p.px(rx, ry, 1, 1, C.light);            // lit FRONT rim. The light follows the FACE — the warrior's lit
    p.px(rx + rw - 1, ry, 1, 1, C.shade);   // edge is his front too, he just happens to face the other way.
  }
}

/** A body with a BUILD: every row's width is interpolated shoulder → waist → hip, so the mass tapers.
 *  A rounded rectangle makes every monster a box; the taper is what turns the brute into a wedge and the
 *  cannon into a bell, and it separates the three families further than any amount of colour does.
 *  `lean` slides the upper rows forward. */
function torso(p, cx, top, h, wTop, wMid, wBot, C, lean = 0) {
  for (let j = 0; j < h; j++) {
    const t = h === 1 ? 0 : j / (h - 1);
    const w = t < 0.5 ? Math.round(wTop + (wMid - wTop) * t * 2)
                      : Math.round(wMid + (wBot - wMid) * (t - 0.5) * 2);
    const off = Math.round(lean * (1 - t));       // the hunch: shoulders forward, hips planted
    const x = cx - (w >> 1) + off;
    p.px(x - 1, top + j, w + 2, 1, C.line);
    p.px(x, top + j, w, 1, C.base);
    p.px(x, top + j, 1, 1, C.light);
    p.px(x + w - 1, top + j, 1, 1, C.shade);
    if (j === 0) p.px(x, top - 1, w, 1, C.line);
    if (j === h - 1) p.px(x, top + h, w, 1, C.line);
  }
}

/** stepped horn / ear / spine / tusk: a taper is the only way to get a point with no anti-aliasing */
function horn(p, x, y, dx, dy, n, C) {
  for (let i = 0; i < n; i++) {
    const w = Math.max(1, (n - i + 1) >> 1);
    const xx = dx < 0 ? x + dx * i - (w - 1) : x + dx * i;
    p.px(xx - 1, y + dy * i, w + 2, 1, C.line); // fringe first, same reason as mass()
    p.px(xx, y + dy * i, w, 1, i > n - 3 ? C.light : C.base);
  }
}

/** two legs; the far one is one ramp step darker, the cheapest way to keep overlapping limbs apart (the
 *  warrior's boots layer does the same). `toe` is how far the foot splays forward. */
function legPair(p, fxx, bxx, top, w, C, toe) {
  const gy = MON_FOOT_Y;
  const one = (lx, R) => {
    p.px(lx - 1, top, w + 2, gy - top + 1, R.line);
    p.px(lx, top, w, gy - top, R.base);
    p.px(lx, top, 1, gy - top, R.light);
    p.px(lx - toe, gy, w + toe, 1, R.base);        // foot, toes forward (left)
    p.px(lx - toe, gy, 1, 1, R.line);
    p.px(lx - toe, gy - 1, 1, 1, R.shade);
    if (d2()) p.px(lx - toe - 1, gy, 1, 1, R.shade); // one claw's worth of toe splay at fine scales
  };
  one(bxx, darker(C));
  one(fxx, C);
}

/** an outlined limb: the fringe pass is what keeps an arm visible where it crosses its own body, which is
 *  most of the time on a monster whose arms hang inside its silhouette */
function limbOut(p, x0, y0, x1, y1, w, C) {
  p.limb(x0 - 1, y0 - 1, x1 - 1, y1 - 1, w + 2, C.line);
  p.limb(x0, y0, x1, y1, w, C.base);
  p.limb(x0, y0, x1, y1, 1, C.light);
}

/** a dithered RING, not a dithered block: a filled checkerboard square reads as a UI panel behind the
 *  sprite, where a ring reads as light coming off it */
function ring(p, x, y, w, h, col, phase = 0) {
  p.dither(x, y, w, 1, col, phase);
  p.dither(x, y + h - 1, w, 1, col, phase);
  p.dither(x, y + 1, 1, h - 2, col, phase);
  p.dither(x + w - 1, y + 1, 1, h - 2, col, phase);
}

/** an eye that reads as ALIVE at 1x: one hot pixel block, a brow above it, a lit corner inside it */
function eye(p, x, y, w, h, col, line) {
  p.px(x - 1, y - 1, w + 2, h + 2, line); // socket
  p.px(x, y, w, h, col);
  // The glint and the pupil are only affordable when pixels remain for the COLOUR: on a 1×1 eye they
  // painted the whole thing back in socket colour, and on a 2×1 they split it white/black — which is how
  // every low-rank monster used to march down the road stone blind.
  if (w * h > 2) {
    p.px(x, y, 1, 1, "#ffffff");
    p.px(x + w - 1, y + h - 1, 1, 1, line); // pupil corner: without it the eye is a lamp, not an eye
  } else if (w * h === 2) {
    p.px(x, y, 1, 1, "#ffffff");            // glint only: one white, one hot
  }
}

// ── family: grunt ────────────────────────────────────────────────────────────────────────
// Small, hunched, more head than body, oversized ears and a cleaver it can barely hold. Reads as "there
// will be twelve of these" — which is exactly what a `fam 0` pull is.
function drawGrunt(p, R, C, ps, level) {
  const D = GRUNT_D[R], FY = MON_FOOT_Y * HR + 1;       // native throughout; FY = last foot row (89)
  const cx = MON_CX * HR + 2;                           // the mass sits a touch behind centre
  const bob = ps.bob * 2, lean = ps.lean * 2, jaw2 = ps.jaw * 2;
  const legTop = FY - D.leg;
  const byBot = legTop + 6;                             // the body swallows the leg roots
  const byTop = byBot - D.bh + bob;
  const bodyL = cx - (D.bw >> 1), bodyR = cx + (D.bw >> 1);
  const hunch = 7;                                      // shoulders pitched over the toes
  const hx = bodyL - (D.hw >> 1) + 4 + lean;            // the head hangs FORWARD of the chest, low
  const hy = byTop - D.hh + 9;

  // back arm first: a scrap of far-side silhouette so the body is not a flat card
  limbF(p, bodyR - 4, byTop + 8, bodyR + 2, byBot - 2, 5, dk(C.hide));
  mLeg(p, bodyR - D.legW - 3, legTop, D.legW, dk(C.hide), 3 + R);   // far leg…
  mLeg(p, bodyL + 3 + (lean >> 1), legTop, D.legW, C.hide, 3 + R);  // …near leg, planted apart
  // the hunched bean of a body: top rows pitched forward, one blob, one outline
  const spans = [];
  for (let j = 0; j < D.bh; j++) {
    const t = j / (D.bh - 1);
    const w = D.bw - Math.round(3 * t) - Math.round(4 * (1 - t) * (1 - t)); // shoulders roll off
    spans.push([-Math.round(hunch * (1 - t)) + ((D.bw - w) >> 1), w]);
  }
  blob(p, bodyL, byTop, spans, C.hide);
  p.fine(bodyL - hunch + 3, byTop + 2, 8, 5, C.hide.light);   // light pooling on the hunched back
  p.fine(bodyR - 7, byTop + 8, 4, D.bh - 14, C.hide.shade);   // the flank turned from the light
  p.fine(bodyL + 1, byBot - 8, D.bw - 4, 2, C.trim.base);     // rag belt…
  p.fine(bodyL + 1, byBot - 6, D.bw - 4, 1, C.trim.shade);
  p.fine(bodyL + 2, byBot - 5, 5, 6, C.trim.base);            // …and the loincloth scrap under it
  p.fine(bodyL + 2, byBot - 2, 5, 3, C.trim.shade);
  const spines = Math.min(3, ((level | 0) / 6) | 0);          // dorsal spines — the level tell, COUNT only
  for (let i = 0; i < spines; i++) hornF(p, bodyR - 8 - i, byTop + 2 + i * 6, 1, -1, 7, C.trim, 4);

  // the HEAD: nearly half the monster. Skull first, then the underbite jaw that owns the silhouette.
  blob(p, hx, hy, [
    [7, D.hw - 13], [4, D.hw - 8], [2, D.hw - 4], [1, D.hw - 2],
    ...Array.from({ length: D.hh - 9 }, () => [0, D.hw]),
    [0, D.hw - 1], [1, D.hw - 3], [2, D.hw - 6], [4, D.hw - 10], [7, D.hw - 14],
  ], C.hide);
  p.fine(hx + 4, hy + 2, D.hw - 12, 3, C.hide.light);         // crown catching the sky
  p.fine(hx + D.hw - 6, hy + 5, 4, D.hh - 10, C.hide.shade);  // the back of the skull
  if (jaw2) p.fine(hx - 2, hy + D.hh - 6, D.hw - 6, jaw2 + 2, "#160f08"); // the maw void when it gapes
  blob(p, hx - 4, hy + D.hh - 5 + jaw2, [                     // the JAW: forward of the skull — underbite
    [0, D.hw - 3], [0, D.hw - 4], [1, D.hw - 6], [3, D.hw - 10],
  ], C.hide);
  p.fine(hx - 3, hy + D.hh - 5 + jaw2, D.hw - 5, 1, C.hide.light); // lip catching light
  for (let k = 0; k < 2 + R; k++)                             // fangs point UP out of the underbite
    p.fine(hx - 1 + k * 5, hy + D.hh - 8 + jaw2, 2, 4, k & 1 ? "#e8dcc0" : "#f2e6c8");
  hornF(p, hx + D.hw - 9, hy + 2, 1, -1, D.ear, C.hide, 6);   // two huge ears swept up and back:
  hornF(p, hx + D.hw - 3, hy + 6, 1, -1, D.ear - 3, C.hide, 5); // the whole grunt read at distance
  p.fine(hx + 2, hy + 5, 10 + R * 2, 2, C.hide.line);         // heavy brow, angry
  p.fine(hx + 1, hy + 6, 3, 1, C.hide.line);                  // …dipping at the snout
  eyeF(p, hx + 4, hy + 7, 4 + R, 3 + R, C.eye, C.hide.line);
  p.fine(hx, hy + 11, 2, 2, C.hide.shade);                    // snout shadow
  p.fine(hx + 1, hy + 12, 2, 1, C.hide.line);                 // nostril

  // front arm dragging a crude chopper — a SLAB on a haft, never loot
  const atk = ps.arm > 2;
  const shx = bodyL - hunch + 5, shy = byTop + 5;
  const bl = 9 + R * 2, bh2 = 14 + R * 3;                     // cleaver blade: width / length
  const fx = Math.max(bh2 + 6 + R * 2, hx - 4 - ps.arm * 2);
  const fy = byBot - 10 + (atk ? 6 : 0);
  limbF(p, shx, shy, fx + 2, fy + 2, D.arm, C.hide);
  p.fine(fx - 1, fy - 1, 8, 8, C.hide.line);                  // the fist
  p.fine(fx, fy, 6, 6, C.hide.base);
  p.fine(fx, fy, 6, 1, C.hide.light);
  // the CLEAVER, unmistakably a blade: an angled slab swept UP-FORWARD at rest (down-forward on the
  // chop), heavier at the tip, grip visible in the fist, cutting edge lit along the leading contour
  p.fine(fx + 2, fy + 5, 3, 5, C.trim.shade);                 // the grip coming out of the fist…
  p.fine(fx + 2, fy + 5, 1, 5, C.trim.light);
  p.fine(fx + 1, fy + 10, 5, 2, C.trim.line);                 // …capped by a pommel nub
  const rootX = fx - 5;
  const rootY = atk ? Math.min(fy + 2, MON_FOOT_Y * HR - bh2) : fy - 4;
  const spans2 = [];
  for (let j = 0; j < bh2; j++) {                             // j runs tip → root
    const heavy = j < 5 ? 4 - (j >> 1) : 0;                   // the tip carries the extra steel
    spans2.push([-Math.round((bh2 - 1 - j) * 0.8) - heavy, bl + heavy]);
  }
  blob(p, rootX, atk ? rootY : rootY - bh2, atk ? spans2.slice().reverse() : spans2, C.trim);
  for (let j = 0; j < bh2; j++) {                             // the honed edge catches the light
    const [dxx, w2] = spans2[j];
    const yy = atk ? rootY + (bh2 - 1 - j) : rootY - bh2 + j;
    p.fine(rootX + dxx, yy, 2, 1, C.trim.light);
    if (j < 5) p.fine(rootX + dxx + w2 - 1, yy, 1, 1, C.trim.shade); // the tip's back edge rolls dark
  }
  p.fine(rootX + spans2[2][0] + 3, atk ? rootY + bh2 - 3 : rootY - bh2 + 2, 2, 2, C.trim.line); // grip hole
  if (atk) {                                                  // the chop's after-image: it came DOWN
    p.fine(rootX - 10, rootY - 6, 2, 6, C.trim.light);
    p.fine(rootX - 4, rootY - 9, 2, 7, C.trim.base);
    p.fine(rootX + 3, rootY - 6, 2, 5, C.trim.light);
  }

  if (R >= 1) { // elite: an iron cap and a shoulder scale — the crowd's sergeant
    blob(p, hx + 3, hy - 5, [[3, D.hw - 12], [1, D.hw - 8], [0, D.hw - 6], [0, D.hw - 6]], C.trim);
    p.fine(hx + 4, hy - 4, D.hw - 10, 1, C.trim.light);
    blob(p, bodyL - hunch + 2, byTop - 1, [[1, 8], [0, 10], [0, 10], [1, 8]], C.trim);
  }
  if (R >= 2) { // boss: a crown of horns and a bone bib — the doubled footprint does the rest
    hornF(p, hx + 6, hy - 1, -1, -1, 8, C.trim, 4);
    hornF(p, hx + (D.hw >> 1), hy - 3, 0, -1, 10, C.trim, 5);
    hornF(p, hx + D.hw - 8, hy - 1, 1, -1, 8, C.trim, 4);
    p.fine(bodyL - 2, byTop + 3, D.bw - 8, 6, C.trim.base);   // the bib
    p.fine(bodyL - 2, byTop + 3, D.bw - 8, 2, C.trim.light);
    for (let k = 0; k < 3; k++) p.fine(bodyL + k * 6, byTop + 9, 3, 3, C.trim.shade); // bone beads
  }
}

// ── family: brute ────────────────────────────────────────────────────────────────────────
// A wall. Twice as wide as it is interesting, head sunk between the shoulders, one arm dragging on the floor
// and a club the size of the grunt. Slow: the idle bob is the only thing that moves.
function drawBrute(p, R, C, ps, level) {
  const D = BRUTE_D[R], FY = MON_FOOT_Y * HR + 1;       // native throughout
  const cx = MON_CX * HR, bob = ps.bob * 2, lean = ps.lean * 2;
  const atk = ps.arm > 2;
  const legTop = FY - D.leg;
  const byBot = legTop + 8;
  const byTop = byBot - D.bh + bob;
  const shL = cx - (D.sw >> 1), shR = cx + (D.sw >> 1); // shoulder extents — the whole personality

  // the maul first, behind everything: a thick shaft and one heavy head. Idle rests it OVER the far
  // shoulder — shaft and head clear of the silhouette, unmistakably a weapon; the attack brings the head
  // down the front in one arc.
  const dark = dk(C.hide);
  const bhx = atk ? shL + 2 + lean : shR + 2;           // the hand that holds it, outside the shoulder edge
  const bhy = atk ? byTop + 14 : byTop + 6;
  const hx2 = atk ? bhx - 14 : bhx + 10;                // where the head ends up
  const hy2 = atk ? bhy + D.maul : bhy - D.maul - 6;
  limbF(p, bhx + 1, bhy + 1, hx2 + 1, hy2 + (atk ? -3 : 5), 4,
        { base: C.trim.shade, light: C.trim.base, shade: C.trim.line, line: C.trim.line });
  const mh = 12 + (R << 1), mx0 = hx2 - (D.maul >> 1), my0 = hy2 - 5;
  blob(p, mx0, my0, Array.from({ length: mh }, (_, j) => {     // a DRUM: rounded ends, not a crate
    const r = Math.min(j, mh - 1 - j);
    const ins = r === 0 ? 2 : r === 1 ? 1 : 0;
    return [ins, D.maul - ins * 2];
  }), C.trim);
  p.fine(mx0 + 1, my0 + 3, 3, mh - 6, C.trim.light);           // the striking face, lit toward the road
  p.fine(mx0 + D.maul - 4, my0 + 3, 3, mh - 6, C.trim.shade);  // the back face rolling away
  p.fine(mx0 + 1, my0 + 2, D.maul - 2, 2, C.trim.line);        // iron binding bands…
  p.fine(mx0 + 1, my0 + mh - 4, D.maul - 2, 2, C.trim.line);
  p.fine(mx0 + 2, my0 + 2, 2, 1, C.trim.light);                // …with their forward rivets glinting
  p.fine(mx0 + 2, my0 + mh - 4, 2, 1, C.trim.light);
  p.fine(mx0 + (D.maul >> 1) - 1, my0 + (atk ? -3 : mh), 2, 3, C.trim.shade); // the strap to the shaft
  if (atk) for (let i = 0; i < 3; i++)                  // the swing's after-image, arcing down the front
    p.fine(hx2 + 6 + i * 4, hy2 - 10 - i * 5, 3, 2, i === 1 ? C.trim.light : C.trim.base);
  // back arm from the far hump up to that hand, then the fist closed around the shaft
  limbF(p, shR - 10, byTop + 4, bhx, bhy, D.arm - 1, dark);
  p.fine(bhx - 2, bhy - 2, 8, 8, dark.line);
  p.fine(bhx - 1, bhy - 1, 6, 6, dark.base);
  p.fine(bhx - 1, bhy - 1, 6, 1, dark.light);

  mLeg(p, cx - (D.hip >> 1) + 1, legTop, D.legW, dk(C.hide), 3 + R);  // pillars under the hips
  mLeg(p, cx + (D.hip >> 1) - D.legW - 1, legTop, D.legW, C.hide, 3 + R);

  // the WEDGE: shoulders → gut → narrow hips, one blob. A brute is a trapezoid; a rectangle is a crate.
  const spans = [];
  for (let j = 0; j < D.bh; j++) {
    const t = j / (D.bh - 1);
    const w = Math.round(D.sw + (D.hip - D.sw) * t * t);       // hips pull in late: the gut stays wide
    spans.push([cx - (w >> 1) - shL + Math.round(lean * (1 - t)), w]);
  }
  blob(p, shL, byTop, spans, C.hide);
  p.fine(shL + 4 + lean, byTop + 2, (D.sw >> 1) - 4, 4, C.hide.light);   // light across the near shoulder
  p.fine(cx + (D.sw >> 2), byTop + 6, (D.sw >> 2) - 2, D.bh - 18, C.hide.shade); // far flank in shadow
  p.fine(cx - 1 + lean, byTop + 4, 2, 10, C.hide.shade);       // sternum crease
  p.fine(shL + 6 + lean, byTop + 9, (D.sw >> 1) - 8, 2, C.hide.shade);   // the underside of each pec:
  p.fine(cx + 3 + lean, byTop + 9, (D.sw >> 1) - 10, 2, C.hide.shade);   // two shadows make a chest
  p.fine(cx - (D.hip >> 1) + 2, byBot - 12, D.hip - 6, 5, C.hide.light); // the gut, catching the light
  p.fine(cx - (D.hip >> 1) - 1, byBot - 6, D.hip + 2, 4, C.trim.shade);  // belt
  p.fine(cx - (D.hip >> 1) - 1, byBot - 6, D.hip + 2, 1, C.trim.line);
  p.fine(cx - 2, byBot - 6, 5, 4, C.trim.light);               // buckle
  p.fine(cx - 1, byBot - 5, 2, 2, C.trim.shade);
  const scars = Math.min(3, ((level | 0) / 6) | 0);            // scars — the level tell
  for (let i = 0; i < scars; i++) {
    p.fine(shL + 8 + i * 7 + lean, byTop + 12 + i * 2, 2, 7, C.hide.line);
    p.fine(shL + 6 + i * 7 + lean, byTop + 15 + i * 2, 6, 2, C.hide.line);
  }

  // shoulder HUMPS on both corners — they are what the arms hang off, and they are why the top of the
  // body reads as shoulders rather than as the top of a crate
  const humpW = (D.sw >> 1) - 4;
  for (const [sx0, ramp] of [[shR - humpW + 4, dark], [shL - 4 + lean, C.hide]]) {
    blob(p, sx0, byTop - 6, [
      [4, humpW - 8], [2, humpW - 4], [1, humpW - 2], [0, humpW], [0, humpW], [0, humpW],
    ], ramp);
    p.fine(sx0 + 3, byTop - 5, humpW - 8, 2, ramp.light);
  }

  // the head: TINY, sunk low between the humps, all brow and jaw
  const hx = cx - (D.hw >> 1) - 4 + lean, hy = byTop - (D.hh >> 1) - 1;
  blob(p, hx, hy, [
    [2, D.hw - 4], [1, D.hw - 2],
    ...Array.from({ length: D.hh - 4 }, () => [0, D.hw]),
    [0, D.hw - 1], [1, D.hw - 3],
  ], C.hide);
  p.fine(hx + 1, hy + 1, D.hw - 3, 2, C.hide.light);           // skull lit on top
  p.fine(hx - 1, hy + 3, D.hw, 2, C.hide.line);                // one heavy brow across both eyes
  eyeF(p, hx + 2, hy + 5, 3 + (R >> 1), 2, C.eye, C.hide.line);
  eyeF(p, hx + D.hw - 6 - (R >> 1), hy + 5, 3 + (R >> 1), 2, C.eye, C.hide.line);
  const my = hy + D.hh - 3 + (ps.jaw ? 2 : 0);                 // the jaw JUTS past the brow
  blob(p, hx - 3, my, [[0, D.hw + 2], [0, D.hw + 1], [1, D.hw - 2]], C.hide);
  p.fine(hx - 2, my, D.hw, 1, C.hide.light);                   // the jut's lit lip
  for (let k = 0; k < 3; k++) p.fine(hx + 1 + k * 4, my + 1, 2, 2, "#f2e6c8"); // teeth hang INTO the jaw,
                                                               // a full row below the eyes
  hornF(p, hx - 2, my - 1, 0, -1, 7 + R, C.trim, 4);           // tusks UP out of the lower jaw,
  hornF(p, hx + D.hw - 2, my - 1, 0, -1, 7 + R, C.trim, 4);    // outside the eye columns

  // front arm: a gorilla arm OUTSIDE the silhouette, knuckles ON the ground in idle
  const fsx = shL + 2 + lean, fsy = byTop + 2;
  const elx = shL - 8 + lean, ely = byTop + (D.bh >> 1);
  const fhx = shL - 12 + lean - (atk ? ps.arm : 0);
  const fhy = atk ? byTop + 10 : FY - D.arm - 2;       // idle: the knuckles rest ON the foot row, never
                                                       // through it — the fist bottom lands at FY-1
  limbF(p, fsx, fsy, elx, ely, D.arm, C.hide);
  limbF(p, elx, ely, fhx + 3, fhy + 3, D.arm - 1, C.hide);
  p.fine(elx + 2, ely + 1, 2, 2, C.hide.shade);                // the crook of the elbow: a JOINT, not a kink
  p.fine(fhx - 1, fhy - 1, D.arm + 4, D.arm + 3, C.hide.line); // the FIST — nearly a second head
  p.fine(fhx, fhy, D.arm + 2, D.arm + 1, C.hide.base);
  p.fine(fhx, fhy, 2, D.arm + 1, C.hide.light);
  for (let i = 2; i <= D.arm; i += 3)                          // knuckles along the top
    p.fine(fhx + i, fhy + 1, 1, 2, C.hide.shade);
  if (d2()) p.fine(fhx + 1, fhy + D.arm + 1, 3, 1, C.hide.shade); // the thumb folded under, fine scales

  if (R >= 1) { // elite: a riveted plate bolted over the far hump
    blob(p, shR - humpW + 2, byTop - 9, [[2, humpW - 4], [1, humpW - 2], [0, humpW], [0, humpW], [0, humpW]], C.trim);
    p.fine(shR - humpW + 4, byTop - 8, humpW - 6, 1, C.trim.light);
    p.fine(shR - humpW + 5, byTop - 6, 2, 2, C.trim.light);    // rivets
    p.fine(shR - 7, byTop - 6, 2, 2, C.trim.light);
  }
  if (R >= 2) { // boss: horns off the skull, a chest plate, a chain across the gut
    hornF(p, hx - 1, hy + 1, -1, -1, 9, C.trim, 5);
    hornF(p, hx + D.hw, hy + 1, 1, -1, 9, C.trim, 5);
    blob(p, cx - (D.sw >> 2) + lean, byTop + 6, Array.from({ length: 10 }, (_, j) =>
      [j >> 3, (D.sw >> 1) - (j >> 3) * 2]), C.trim);
    p.fine(cx - (D.sw >> 2) + 1 + lean, byTop + 7, (D.sw >> 1) - 2, 2, C.trim.light);
    for (let i = 0; i < (D.hip >> 2); i++)                     // the chain, link by link
      p.fine(cx - (D.hip >> 1) + 2 + i * 4, byBot - 11 + ((i & 1) << 1), 3, 3, i & 1 ? C.trim.light : C.trim.base);
  }
}

// ── family: glass cannon ─────────────────────────────────────────────────────────────────
// Stilts, a robe and a light source. Nothing about it says "hit me and I survive" — which is the point: it
// pays the most renown and dies to one good swing.
function drawCannon(p, R, C, ps, level, frame) {
  const D = CANNON_D[R], FY = MON_FOOT_Y * HR + 1;      // native throughout
  const cx = MON_CX * HR + 2, lean = ps.lean * 2;
  const hover = [0, -2, 1, -1][frame % 4];              // it does not stand — it DRIFTS
  const atk = ps.arm > 2;
  const hemBot = FY - 8 + hover;                        // the hem floats WELL clear of its own shadow
  const robeTop = hemBot - D.robeH;

  // the robe IS the body: one bell, no legs anywhere under it
  const spans = [];
  for (let j = 0; j < D.robeH; j++) {
    const t = j / (D.robeH - 1);
    const w = Math.round(D.bw + (D.hem - D.bw) * (0.35 * t + 0.65 * t * t));
    spans.push([-(w >> 1) + Math.round(lean * (1 - t)), w]);
  }
  blob(p, cx, robeTop, spans, C.hide);
  for (let i = 0; i < 5; i++)                           // the hem hangs in TATTERS, points drifting
    hornF(p, cx - (D.hem >> 1) + 3 + i * ((D.hem - 6) >> 2), hemBot + ((i + frame) % 3 === 0 ? 3 : 1), 0, 1, 4 + ((i * 5) % 3), C.hide, 4);
  p.fine(cx - (D.bw >> 1) + lean, robeTop + 3, D.bw - 2, 4, C.hide.light);  // lit yoke at the shoulders
  p.fine(cx - 4 + lean, robeTop + 8, 2, D.robeH - 14, C.hide.shade);        // two long falls of cloth…
  p.fine(cx + 3 + lean, robeTop + 10, 2, D.robeH - 18, C.hide.shade);       // …make the bell DRAPE
  p.fine(cx + (D.hem >> 2), robeTop + (D.robeH >> 1), (D.hem >> 2), D.robeH >> 2, C.hide.shade); // far side
  p.fine(cx - (D.hem >> 1) + 2, hemBot - 3, D.hem - 4, 2, C.hide.shade);    // gathering above the hem
  const runes = Math.min(3, ((level | 0) / 5) | 0);     // runes down the robe — the level tell, and the
  for (let i = 0; i < runes; i++) {                     // only pure light on the cloth
    const ry = robeTop + 10 + i * 8, rx = cx - 2 + ((i & 1) << 1);
    p.fine(rx, ry, 4, 2, C.glow);
    p.fine(rx + 1, ry - 2, 2, 2, C.glow);
    p.fine(rx + (i & 1 ? 0 : 2), ry + 2, 2, 2, C.glow);
  }

  // the hood: a cowl with a BLACK VOID where the face should be, and two coals hanging in it
  const hx = cx - (D.hw >> 1) - 1 + lean, hy = robeTop - D.hh + 7;
  blob(p, hx, hy, [
    [5, D.hw - 9], [3, D.hw - 6], [2, D.hw - 4], [1, D.hw - 2],
    ...Array.from({ length: D.hh - 6 }, () => [0, D.hw]),
    [0, D.hw], [1, D.hw],
  ], C.hide);
  hornF(p, hx + D.hw - 5, hy - 1, 1, -1, 7 + R * 2, C.hide, 5);   // the peak, swept back off the crown
  p.fine(hx + 2, hy + 1, 6, 3, C.hide.light);                     // moonlight on the cowl
  const vw = D.hw - 7, vh = D.hh - 8;
  p.fine(hx + 2, hy + 5, vw, vh, "#0b0a12");                      // the void
  p.fine(hx + 2, hy + 4, vw, 1, C.hide.shade);                    // the brim overhanging it: the darkness
                                                                  // is INSIDE something
  const ew = 4 + (R >> 1);                                        // two BURNING coals, no face
  for (const ex of [hx + 3, hx + 5 + ew]) {
    p.fine(ex - 1, hy + 7, ew + 2, 4, "#0b0a12");                 // re-cut the socket…
    p.fine(ex, hy + 8, ew, 3, C.eye);                             // …so the glow floats in it
    p.fine(ex + 1, hy + 7, ew - 2, 1, C.eye);                     // flame licking upward
    p.fine(ex, hy + 8, 2, 1, "#ffffff");
  }
  if (ps.jaw) p.fine(hx + 3, hy + 5 + vh - 2, vw - 2, 1, C.glow); // it lights up before it speaks

  // the staff: planted DOWN the front, orb burning at the top — the family read at any distance
  // (the boss's orb is clamped down off the frame edge so its spokes never clip)
  const stx = cx - (D.hem >> 1) - 4, orbY = Math.max(D.orb + 12, hy - 4 - (D.orb >> 1));
  p.fine(stx - 1, orbY + 4, 4, hemBot - orbY + 2, C.trim.line);
  p.fine(stx, orbY + 4, 2, hemBot - orbY, C.trim.base);
  p.fine(stx, orbY + 4, 1, hemBot - orbY, C.trim.light);
  p.fine(stx - 2, orbY + 8, 6, 2, C.trim.shade);                  // a binding ring below the crook
  // the casting arm: a thin sleeve out to the staff, ending in a skeletal claw around it
  limbF(p, cx - (D.bw >> 1) + 2 + lean, robeTop + 6, stx + 4, robeTop + 10, 4, C.hide);
  p.fine(stx - 1, robeTop + 9, 6, 4, C.trim.light);               // the claw
  p.fine(stx, robeTop + 10, 1, 2, C.trim.shade);                  // gaps between bones
  p.fine(stx + 3, robeTop + 10, 1, 2, C.trim.shade);
  // the ORB: the family's signature, so it gets real geometry — circle spans inside a dark halo, a
  // white-hot heart high on the sphere, and a crescent of the eye-colour cooling the lower rim
  const pulse = [0, 1, 0, 2][frame % 4], rr = D.orb + 2 + pulse;            // diameter
  const ox0 = stx - (rr >> 1), oy0 = orbY - (rr >> 1);
  p.fine(ox0 - 1, oy0 + (rr >> 1), 2, (rr >> 1) + 2, C.trim.base);          // the crook's two prongs
  p.fine(ox0 + rr - 1, oy0 + (rr >> 1), 2, (rr >> 1) + 2, C.trim.base);
  const orbSpans = [];
  for (let j = 0; j < rr; j++) {
    const dyy = j + 0.5 - rr / 2;
    const half = Math.sqrt(Math.max(0, (rr / 2) * (rr / 2) - dyy * dyy));
    const w2 = Math.max(2, Math.round(half * 2));
    orbSpans.push([Math.round((rr - w2) / 2), w2]);
  }
  blob(p, ox0, oy0, orbSpans, { base: C.glow, line: "#0b0a12", light: C.glow, shade: C.glow });
  for (let j = (rr >> 1) + 1; j < rr - 1; j++) {                            // the crescent
    const [dxx, w2] = orbSpans[j];
    p.fine(ox0 + dxx + 1, oy0 + j, w2 - 2, 1, C.eye);
  }
  p.fine(ox0 + (rr >> 2), oy0 + (rr >> 2), 3, 2, "#ffffff");                // the white-hot heart
  p.fine(ox0 + (rr >> 2) + 1, oy0 + (rr >> 2) - 1, 1, 1, "#ffffff");
  for (let d = 3; d < 6 + (frame & 1); d++) {                     // four spokes of light off it
    p.fine(stx, orbY - (rr >> 1) - d, 1, 1, C.glow);
    p.fine(stx, orbY + (rr >> 1) + d, 1, 1, C.glow);
    p.fine(stx - (rr >> 1) - d, orbY, 1, 1, C.glow);
    p.fine(stx + (rr >> 1) + d, orbY, 1, 1, C.glow);
  }
  if (atk) { // the BOLT: fire has left the orb and is on its way to the hero
    for (let i = 0; i < 12; i += 2) p.fine(stx - 8 - i, orbY + 6 + (i >> 2), 3, 2, i & 2 ? C.glow : C.eye);
    p.fine(stx - 22, orbY + 8, 4, 4, C.eye);
    p.fine(stx - 21, orbY + 9, 2, 2, "#ffffff");
    p.fine(stx - 14, orbY + 3, 2, 2, C.glow);                     // sparks shed in the wake
    p.fine(stx - 12, orbY + 13, 2, 2, C.glow);
  }
  if (R >= 1) for (let i = 0; i < 3; i++)                         // elite: a crown of spines on the cowl
    hornF(p, hx + 4 + i * ((D.hw - 8) >> 1), hy + 1 - (i === 1 ? 2 : 0), 0, -1, 5, C.trim, 3);
  if (R >= 2) for (let i = 0; i < 3; i++) {                       // boss: runes hanging in the air beside
    const rx = cx + (D.hem >> 1) + 6, ry = robeTop + 4 + i * 14 + ((frame + i) & 1) * 2; // it — the road
    p.fine(rx, ry, 6, 2, C.glow);                                 // itself is hostage
    p.fine(rx + 2, ry - 2, 2, 6, C.glow);
    p.fine(rx - 2, ry + (i & 1 ? -1 : 3), 2, 2, C.glow);
  }
}

// ── death ────────────────────────────────────────────────────────────────────────────────
// A monster corpse is authored, not the standing pose knocked over: the point of frame 4 is that the road
// behind you is LITTERED, so it has to read as a heap in one glance. Sized by rank like everything else.
const CORPSE_D = [ // [family][rank] = [body w, body h] — NATIVE px; the head is laid end-to-end with it
  [[24, 12], [30, 14], [40, 20]],
  [[36, 16], [42, 18], [52, 24]],
  [[28, 12], [34, 14], [44, 20]],
];
function drawCorpse(p, fam, R, C, level, frame) {
  const [w, h] = CORPSE_D[fam][R];                     // native heap size
  const FY = MON_FOOT_Y * HR + 1;
  const hw = Math.max(12, (w >> 2) + 8);               // the head, big enough to read on its own
  const left = MON_CX * HR - ((hw + w) >> 1) - 2;      // head + body laid end to end, centred
  const x = left + hw + 2, y = FY - h;                 // x = where the body starts
  // the heap: a slumped mass, high at the shoulders, pressed wide and flat at the ground
  blob(p, x, y, Array.from({ length: h }, (_, j) => {
    const t = j / (h - 1);
    const wj = Math.round(w * (0.5 + 0.5 * t));
    return [Math.round((w - wj) * 0.3), wj];
  }), C.hide);
  p.fine(x + 3, y + 1, (w >> 1), 2, C.hide.light);     // rim light along the top of the heap
  p.fine(x + (w >> 2), y + h - 3, (w >> 1), 2, C.hide.shade); // dead weight pressed into the road
  for (let i = 0; i < ((w / 12) | 0); i++)             // slump creases: the mass SETTLED and folded —
    p.fine(x + 6 + i * 10, y + 2, 2, h - 5, C.hide.shade); // it did not just tip over rigid
  limbF(p, x + 4, y + 3, left - 2, FY - 3, 4, dk(C.hide));      // the arm it died reaching with…
  p.fine(left - 4, FY - 5, 5, 4, C.hide.shade);                 // …and the open hand on the end of it
  limbF(p, x + w - 6, y + 4, x + w + 5, FY - 8, 4, dk(C.hide)); // a leg folded out the back
  // the head, tipped over CLEAR of the mass with its own outline — touching, it is just more body
  const hy = FY - hw + 2;
  blob(p, left, hy, Array.from({ length: hw - 2 }, (_, j) => {
    const r = Math.min(j, hw - 3 - j);
    const ins = r === 0 ? 3 : r === 1 ? 2 : r === 2 ? 1 : 0;
    return [ins, hw - ins * 2];
  }), C.hide);
  p.fine(left + 2, hy + 1, hw - 6, 2, C.hide.light);
  const ex = left + (hw >> 1) - 3, ey = hy + (hw >> 1) - 4;     // a true ✕ over the near eye, native-sized
  for (let i = 0; i < 5; i++) {
    p.fine(ex + i, ey + i, 2, 2, C.hide.line);
    p.fine(ex + 4 - i, ey + i, 2, 2, C.hide.line);
  }
  p.fine(left + 2, FY - 6, hw - 6, 2, "#f2e6c8");               // teeth, lolling open…
  for (let k = 0; k < hw - 8; k += 3) p.fine(left + 3 + k, FY - 5, 1, 1, C.hide.shade); // …one by one
  p.fine(left + 3, FY - 4, 4, 2, GORE.base);                    // the tongue is out over the jaw
  if (fam === 0) { hornF(p, left + 2, hy + 2, -1, -1, 9, C.hide, 4); hornF(p, left + hw - 4, hy, 1, -1, 7, C.hide, 4); } // ears
  if (fam === 1) { hornF(p, left + 1, hy + 3, 0, -1, 8, C.trim, 4); hornF(p, left + hw - 3, hy + 3, 0, -1, 8, C.trim, 4); } // tusks
  if (fam === 2) { // the cannon's staff, fallen across the heap, the orb guttering out
    p.fine(x - 4, FY - 10, w + 6, 2, C.trim.base);
    p.fine(x - 4, FY - 10, w + 6, 1, C.trim.light);
    p.fine(x - 8, FY - 12, 5, 5, "#0b0a12");
    p.fine(x - 7, FY - 11, 3, 3, C.glow);
  }
  drawBloodInto(p, "pool", { frame: 3 + (frame & 1), amount: 3 + R * 4, seed: fam * 7 + R, cy: MON_GROUND_Y });
  drawBloodInto(p, "splatter", { amount: 2 + R * 3, seed: fam * 13 + R });
}

/**
 * Draw one monster frame with its TOP-LEFT CORNER at (x, y) — NOT its feet, and NOT its centre. Same
 * convention as drawWarrior, and it is called out here because the caller passing ground coordinates
 * straight in is exactly how these sprites once rendered off-canvas. The feet land on row MON_FOOT_Y of an
 * MON_W × MON_H box, so ground → corner is `y - MON_GROUND_Y * scale` (or just `y - MON_H * scale` for the
 * bottom edge, as the world renderer does).
 *
 * opts = {
 *   family: 0 grunt | 1 brute | 2 cannon   — owns the silhouette
 *   rank:   0 normal | 1 elite | 2 boss    — owns the size and the ornament
 *   level:  int, depth-scaled              — owns the palette band and a few spines/runes only
 *   frame:  0,1,2 idle · 3 attack · 4 death (MON_ATTACK_FRAME / MON_DEATH_FRAME)
 *   scale:  int ≥ 1
 *   facing: -1 (default) faces LEFT, into the hero walking in from the left; +1 mirrors it
 *   hurt:   flash the whole sprite toward red
 *   dead:   force the death pose and the corpse colour map, whatever `frame` says
 * }
 * Same inputs → same pixels: no clocks and no randomness anywhere in here.
 * Returns { w, h } in device pixels, like drawWarrior.
 */
export function drawMonster(ctx, x, y, opts = {}) {
  DETAIL = opts.detail === 2 ? 2 : 1;
  const fam = Math.max(0, Math.min(2, opts.family | 0));
  const R = Math.max(0, Math.min(2, opts.rank | 0));
  const level = Math.max(0, opts.level | 0);
  const scale = Math.max(1, opts.scale | 0 || 1);
  const facing = opts.facing === 1 ? 1 : -1;   // −1 is the DEFAULT here (monsters face the oncoming hero)
  let frame = Math.max(0, Math.min(MON_FRAMES - 1, opts.frame | 0));
  const dead = !!opts.dead || frame === MON_DEATH_FRAME;
  const C = MON_PALS[fam][bandOf(level)];
  const recolor = dead ? (c) => mix(c, "#2b2430", 0.45)
    : opts.hurt ? (c) => mix(c, "#ff5a5a", 0.55)
    : null;
  ctx.imageSmoothingEnabled = false;
  // facing +1 is the MIRROR (the art is authored left-facing), so the pen is handed the inverse
  const p = pen(ctx, x, y, scale, facing === 1 ? -1 : 1, false, recolor, MON_W, MON_H);

  // contact shadow, dithered like the warrior's; wider for a boss, wider still for a heap
  const sw = (dead ? 25 + R * 7 : [15, 19, 28][R] + (fam === 1 ? 8 : 0)) * HR;
  for (let i = 0; i < sw; i += 2)
    p.fraw(MON_CX * HR - (sw >> 1) + i, MON_GROUND_Y * HR + ((i & 2) ? 1 : 0), 1, 1, "#1a1420");

  if (dead) drawCorpse(p, fam, R, C, level, opts.frame | 0);
  else {
    const ps = MON_POSES[Math.min(frame, MON_POSES.length - 1)];
    if (fam === 0) drawGrunt(p, R, C, ps, level);
    else if (fam === 1) drawBrute(p, R, C, ps, level);
    else drawCannon(p, R, C, ps, level, frame);
  }
  return { w: MON_W_N * scale, h: MON_H_N * scale };
}

/** The whole monster strip in one call — 3 idle, attack, death — for a bestiary widget or an offscreen bake. */
export function drawMonsterSheet(ctx, x, y, opts = {}) {
  const scale = Math.max(1, opts.scale | 0 || 1);
  for (let f = 0; f < MON_FRAMES; f++) drawMonster(ctx, x + f * MON_W_N * scale, y, { ...opts, frame: f, scale });
  return { w: MON_FRAMES * MON_W_N * scale, h: MON_H_N * scale, cells: MON_FRAMES };
}

// ══ PROPS ════════════════════════════════════════════════════════════════════════════════
// The non-combat tiles. Same pixel style, same frame box as the monsters (so the world renderer converts
// ground → corner once), but authored small and centred: a chest must not compete with a boss.
const WOOD  = { base: "#8a5a32", shade: "#5a381d", light: "#b5844f", line: "#2a1a0c" };
const STONE = { base: "#8d8d96", shade: "#5d5d66", light: "#c0c0c8", line: "#2b2b32" };
const IRON  = MATERIALS[1];
const GOLD  = MATERIALS[5];
const GEM   = { base: "#7d5ae0", shade: "#4a2f9a", light: "#c4b0ff", line: "#1d1240" };
const FIRE  = { base: "#ff7a18", shade: "#c23a06", light: "#ffd24a", line: "#5a1a02" };
const WATER = { base: "#3f8fd0", shade: "#245e94", light: "#9fdcff", line: "#123049" };
const GALE  = { base: "#5c6c80", shade: "#3a4452", light: "#8fa5bb", line: "#1a202a" };

function propHazard(p, f) { // a spiked, burning pit — the tile that chips you if you do not dodge
  const gy = MON_FOOT_Y;
  p.px(MON_CX - 9, gy, 18, 1, "#20161a");                       // scorched ground
  p.dither(MON_CX - 11, gy - 1, 22, 2, "#3a2418", f & 1);
  for (let i = 0; i < 4; i++) {                                  // spikes, alternating heights
    const sx = MON_CX - 8 + i * 5, sh = 5 + (i & 1) * 3;
    horn(p, sx, gy - 1, 0, -1, sh, IRON);
    p.px(sx, gy - 2, 1, 1, IRON.shade);                          // soot climbing the root of each spike
  }
  for (let i = 0; i < 18; i++) {                                 // flame tongues off the coal bed
    const t = FLAME[(i + f * 3) % FLAME.length] + 2;
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, t, FIRE.shade);
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, (t >> 1) + 1, FIRE.base);
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, 1, FIRE.light);
  }
  p.px(MON_CX - 8, gy - 1, 16, 1, FIRE.shade);                   // embers under it all
  for (let i = 0; i < 16; i += 4)                                // hot coals crawling along the ember row —
    p.px(MON_CX - 8 + i + f, gy - 1, 1, 1, FIRE.light);          // the pit breathes even between flame frames
  p.px(MON_CX + 9, gy - 2, 3, 2, "#d8cfb4");                     // a half-buried skull at the rim:
  p.px(MON_CX + 10, gy - 1, 1, 1, "#1a1510");                    // somebody did not dodge
}

function propCache(p, f) { // a chest, lid ajar, with a pulse of gold coming out of the gap
  const gy = MON_FOOT_Y, w = 16, h = 9, x = MON_CX - (w >> 1), y = gy - h;
  const lift = 1 + (f % 3 === 2 ? 1 : 0);                         // the lid breathes: it is not empty
  p.px(x - 1, y - 1, w + 2, h + 2, WOOD.line);
  p.px(x, y, w, h, WOOD.base);
  p.px(x, y, w, 1, WOOD.light);
  p.px(x + 5, y, 1, h, WOOD.shade);                               // two plank seams, not five: at 16 px a
  p.px(x + 11, y, 1, h, WOOD.shade);                              // striped box stops being a chest
  p.px(x + 2, y, 2, h, IRON.base);                                // iron bands
  p.px(x + 2, y, 2, 1, IRON.light);
  p.px(x + w - 4, y, 2, h, IRON.base);
  p.px(x + w - 4, y, 2, 1, IRON.light);
  p.px(x + 4, y + 3, 1, 2, WOOD.shade);                           // short grain ticks between the seams,
  p.px(x + 10, y + 5, 1, 2, WOOD.shade);                          // staggered — so the planks read as wood
  p.px(x + 14, y + 2, 1, 2, WOOD.shade);                          // and not as a striped box
  p.px(x + 2, y + h - 2, 2, 1, IRON.shade);                       // the bands sit proud of the wood: they
  p.px(x + w - 4, y + h - 2, 2, 1, IRON.shade);                   // darken where they wrap under the belly
  p.px(x + ((w >> 1) - 1), y + 2, 3, 4, GOLD.base);               // lock plate, front and centre
  p.px(x + ((w >> 1) - 1), y + 2, 3, 1, GOLD.light);
  p.px(x + (w >> 1), y + 3, 1, 2, GOLD.line);                     // keyhole
  if (f === 2) p.px(x + (w >> 1) - 1, y + 2, 1, 1, "#ffffff");    // the lock glints exactly when the lid
                                                                  // breathes: one beat, two tells
  p.dither(x + 1, y - 1 - lift, w - 2, 1 + lift, GOLD.light, f & 1); // the glow escaping the seam
  p.px(x - 1, y - 4 - lift, w + 2, 4, WOOD.line);                 // the lid, tipped back off the seam
  p.px(x, y - 3 - lift, w, 3, WOOD.base);
  p.px(x, y - 3 - lift, w, 1, WOOD.light);
  p.px(x + 2, y - 3 - lift, 2, 3, IRON.base);
  p.px(x + w - 4, y - 3 - lift, 2, 3, IRON.base);
  if (d2()) { p.px(x + 6, y - 2 - lift, 1, 1, IRON.light); p.px(x + 10, y - 2 - lift, 1, 1, IRON.light); } // lid nails
  for (let i = 0; i < 5; i++) p.px(x + 3 + i * 3, y - 6 - lift - ((f + i) % 3), 1, 1, GOLD.light); // motes
}

function propShrine(p, f) { // a fountain: wide steps, a narrow pillar, a bowl of water on top of it.
  // Base → pillar → bowl is the whole trick: a stack of same-width slabs reads as a bathtub, which is
  // what this was before the pillar went in.
  const gy = MON_FOOT_Y;
  const step = (wd, yy, hh, C) => {
    p.px(MON_CX - (wd >> 1) - 1, yy - 1, wd + 2, hh + 1, STONE.line);
    p.px(MON_CX - (wd >> 1), yy, wd, hh, C.base);
    p.px(MON_CX - (wd >> 1), yy, wd, 1, C.light);
    p.px(MON_CX - (wd >> 1), yy, 1, hh, C.light);
    p.px(MON_CX + (wd >> 1) - 1, yy, 1, hh, C.shade);
  };
  step(18, gy - 1, 2, STONE);           // ground step
  step(13, gy - 4, 3, STONE);           // plinth
  step(6, gy - 10, 6, STONE);           // pillar
  p.px(MON_CX - 2, gy - 8, 1, 2, STONE.shade);                    // a crack up the pillar and one on the
  p.px(MON_CX + 3, gy - 3, 2, 1, STONE.shade);                    // plinth: old stone, not fresh masonry
  if (d2()) { p.px(MON_CX - 8, gy - 1, 1, 1, "#4f7a3a"); p.px(MON_CX + 5, gy - 2, 1, 1, "#4f7a3a"); } // moss
  step(14, gy - 15, 5, STONE);          // bowl
  p.px(MON_CX - 6, gy - 14, 12, 3, WATER.base);
  p.dither(MON_CX - 6, gy - 14, 12, 2, WATER.light, f & 1);       // surface, catching the sky
  p.px(MON_CX - 5 + f * 4, gy - 14, 2, 1, "#ffffff");             // one hard specular WALKING the surface:
                                                                  // the read that the water is moving
  for (const sx of [MON_CX - 7, MON_CX + 5]) {                    // water running over the lip
    p.px(sx, gy - 12, 2, 3 + ((f + 1) % 3), WATER.base);
    p.px(sx, gy - 12, 1, 2, WATER.light);
    p.px(sx, gy - 4, 2, 1, WATER.shade);                          // and the plinth stained dark where it lands
  }
  p.px(MON_CX - 1, gy - 18 - (f % 3), 2, 2, WATER.light);         // the droplet, rising
  p.px(MON_CX, gy - 21 - (f % 3), 1, 1, WATER.light);
  for (let i = 0; i < 5; i++) {                                   // a blessing hanging over it: loose motes,
    const t = (i + f) % 5;                                        // because a dashed rectangle up there
    p.px(MON_CX - 7 + i * 3, gy - 19 - t, 1, 1, WATER.light);     // reads as a UI box, not as light
  }
}

function propForge(p, f) { // an anvil on a stump over a coal bed; sparks hop off the face
  const gy = MON_FOOT_Y;
  p.px(MON_CX - 5, gy - 5, 10, 5, WOOD.base);                     // stump
  p.px(MON_CX - 5, gy - 5, 10, 1, WOOD.light);
  p.px(MON_CX - 2, gy - 4, 1, 3, WOOD.shade);                     // split grain down the stump: a plain
  p.px(MON_CX + 1, gy - 3, 1, 2, WOOD.shade);                     // brown block reads as a crate, not a log
  p.px(MON_CX - 5, gy - 1, 10, 1, WOOD.line);
  p.px(MON_CX - 8, gy - 12, 15, 3, IRON.base);                    // anvil face + horn
  p.px(MON_CX - 8, gy - 12, 15, 1, IRON.light);
  p.px(MON_CX - 8, gy - 10, 15, 1, IRON.shade);                   // the face's underside rolls into shadow
  p.px(MON_CX - 10, gy - 11, 2, 1, IRON.base);
  p.px(MON_CX - 10, gy - 11, 1, 1, IRON.light);                   // a glint off the horn's tip
  p.px(MON_CX - 3, gy - 9, 5, 3, IRON.shade);                     // waist
  p.px(MON_CX - 6, gy - 6, 11, 2, IRON.base);                     // base
  p.px(MON_CX - 6, gy - 6, 11, 1, IRON.light);
  p.px(MON_CX - 2, gy - 13, 5, 1, f === 1 ? FIRE.light : FIRE.base); // the WORKPIECE on the face, pulsing
  p.px(MON_CX - 2, gy - 13, 1, 1, FIRE.shade);                    // as it cools — this is a forge mid-job,
  if (f === 0) p.px(MON_CX + 1, gy - 14, 1, 1, "#ffffff");        // and the hammer lands white-hot on f0
  if (d2()) { p.px(MON_CX - 7, gy - 3, 1, 3, IRON.shade); p.px(MON_CX - 8, gy - 1, 1, 1, IRON.base); } // a
                                                                  // poker leaning on the stump, fine scales
  p.px(MON_CX + 6, gy - 3, 10, 3, FIRE.shade);                    // coal bed beside it
  p.dither(MON_CX + 6, gy - 4, 10, 3, FIRE.base, f & 1);
  for (let i = 0; i < 6; i++) {                                    // sparks off the face, on a fixed arc
    const t = (i + f * 2) % 6;
    p.px(MON_CX - 6 + t * 2, gy - 13 - FLAME[(i + f) % FLAME.length], 1, 1, t & 1 ? FIRE.light : FIRE.base);
  }
  p.px(MON_CX + 2, gy - 16 - (f % 3), 2, 4, IRON.base);            // the hammer, mid-fall
  p.px(MON_CX + 2, gy - 16 - (f % 3), 2, 1, IRON.light);
  p.px(MON_CX + 3, gy - 13 - (f % 3), 1, 4, WOOD.base);
}

function propRelic(p, f) { // a gem floating over nothing at all, throwing spokes of light
  const gy = MON_FOOT_Y, cy = gy - 14 - (f % 3);
  for (let i = 0; i < 9; i += 2) p.raw(MON_CX - 4 + i, gy, 1, 1, "#1a1420"); // it still casts a shadow
  const spoke = 5 + (f % 3);
  for (let i = 2; i < spoke; i++) {                                // four spokes, breathing with the frame
    p.px(MON_CX, cy - 2 - i, 1, 1, GEM.light);
    p.px(MON_CX, cy + 4 + i, 1, 1, GEM.light);
    p.px(MON_CX - 3 - i, cy + 1, 1, 1, GEM.light);
    p.px(MON_CX + 3 + i, cy + 1, 1, 1, GEM.light);
  }
  const rows = [3, 5, 7, 7, 5, 3];                                  // a cut stone: a stepped diamond,
                                                                    // big enough to read inside its halo
  rows.forEach((w, j) => {
    p.px(MON_CX - (w >> 1) - 1, cy - 1 + j, w + 2, 1, GEM.line);
    p.px(MON_CX - (w >> 1), cy - 1 + j, w, 1, j < 2 ? GEM.light : GEM.base);
    p.px(MON_CX - (w >> 1), cy - 1 + j, 1, 1, GEM.light);
  });
  p.px(MON_CX - 1, cy + 3, 3, 1, GEM.shade);                        // the cut below the girdle: one dark
                                                                    // facet is what says CARVED, not blown
  p.px(MON_CX - 1, cy + 1, 2, 1, "#ffffff");                        // core
  const sp = [[3, -1], [-4, 2], [2, 3]][f];                         // a single sparkle walking the facets
  p.px(MON_CX + sp[0], cy + sp[1], 1, 1, "#ffffff");                // frame to frame — the idle glitter
  if (d2()) p.px(MON_CX - 2, cy, 1, 1, "#ffffff");                  // an inner reflection at fine scales
  ring(p, MON_CX - 6, cy - 3, 13, 11, GEM.base, f & 1);             // halo: a ring, so the cut stone
                                                                    // inside it is still a stone
  for (let i = 0; i < 3; i++) p.px(MON_CX - 3 + i * 3, cy + 7 - ((f + i) % 4) * 2, 1, 1, GEM.light); // motes
}

function propFork(p, f) { // a signpost where the road splits: left board is the safe road, right is greed
  const gy = MON_FOOT_Y, px0 = MON_CX + 1;
  for (let i = 0; i < 10; i++) {                                    // the split itself, drawn in the dirt
    p.raw(MON_CX - 12 + i, gy, 1, 1, "#2b2018");
    p.raw(MON_CX - 12 + i, gy - 1 - (i >> 1), 1, 1, "#2b2018");
  }
  p.px(px0, gy - 20, 2, 21, WOOD.base);                             // post
  p.px(px0, gy - 20, 1, 21, WOOD.light);
  p.px(px0 + 1, gy - 14, 1, 1, WOOD.shade);                         // grain nicks down the post, in the gaps
  p.px(px0, gy - 6, 1, 2, WOOD.shade);                              // between the boards
  p.px(px0 - 1, gy - 1, 4, 1, WOOD.line);
  const board = (by, dir, C) => {                                   // an arrow board: rect + a pointed end
    const w = 10, bx = dir < 0 ? px0 - w - 1 : px0 + 2;
    p.px(bx - 1, by - 1, w + 2, 6, WOOD.line);
    p.px(bx, by, w, 4, C.base);
    p.px(bx, by, w, 1, C.light);
    p.px(bx, by + 3, w, 1, C.shade);                                // underside in shadow: the board is a
                                                                    // plank with thickness, not a sticker
    const tip = dir < 0 ? bx - 1 : bx + w;
    p.px(tip, by + 1, 1, 2, C.base);
    p.px(tip + (dir < 0 ? -1 : 1), by + 2, 1, 1, C.base);
    for (let i = 2; i < w - 1; i += 3) p.px(bx + i, by + 2, 2, 1, C.line); // "writing"
  };
  board(gy - 19, -1, WOOD);
  board(gy - 12, 1, { base: "#a05a2a", shade: WOOD.shade, light: "#d08a4a", line: WOOD.line });
  p.px(px0 - 1, gy - 21, 4, 1, WOOD.shade);                          // cap
  if (f & 1) p.px(px0 + 3, gy - 22, 1, 1, GOLD.light);               // a glint off the nail: it is not dead
  if (f === 2) p.px(px0 + 3, gy - 11, 1, 1, GOLD.light);             // …and the greed board's nail answers
                                                                     // on the off-beat
  if (d2()) { p.px(MON_CX - 10, gy - 1, 1, 1, "#4f7a3a"); p.px(MON_CX - 5, gy - 2, 1, 1, "#4f7a3a"); } // grass
                                                                     // tufts where the road splits
}

function propGale(p, f) { // a windstorm parked over the road — a storm you WALK INTO, deliberately not a creature
  const gy = MON_FOOT_Y, cx = MON_CX;
  for (let i = 0; i < 11; i++)                                      // the road scoured in streaks beneath it,
    p.raw(cx - 11 + i * 2, gy, 2, 1, (i + f) % 3 ? "#2b2018" : "#3a3026"); // grit crawling with the wind
  for (const [ty, ln, ph] of [[4, 4, 0], [7, 5, 1], [10, 4, 2]]) {  // trails streaming out ahead of the roll,
    const t = (f + ph) % 3;                                          // each tearing off on its own beat
    p.px(cx - 13 - t * 2, gy - ty, ln, 1, GALE.shade);
    p.px(cx - 13 - t * 2, gy - ty, 1, 1, GALE.base);                 // the torn head is a step lighter: dust
  }                                                                  // thinning out, not a floating stick
  for (const [ty, ph] of [[5, 0], [9, 1]]) {                         // …and short inflow dashes behind it —
    const t = (f + ph) % 3;                                          // the storm eats road as it goes
    p.px(cx + 12 + t, gy - ty, 3, 1, GALE.shade);
  }
  p.dither(cx - 8, gy - 1, 16, 1, "#3a3026", f);                     // the dust skirt where it meets the road
  const ROWS = [ // the roll itself, bottom to top: [rise, half-width, lean] — fat at the shoulder, and the
                 // whole crest streamed FORWARD (the monsters' left) so the thing is going somewhere
    [2, 5, 0], [3, 8, 0], [4, 10, 0], [5, 11, 0], [6, 12, 0], [7, 12, 0], [8, 12, -1],
    [9, 12, -1], [10, 11, -2], [11, 10, -2], [12, 8, -3], [13, 6, -5], [14, 4, -7],
  ];
  const LS = [-2, 4, -6, 2, -8, 5, -3, 1, -6, 3, -1, 2, 0];          // where each row's lit rim sits
  const THROAT = [-1, 0, 1, 2, 2, 1, 0, -1, -2, -2, -1, 0, 1];       // the eye of it, a slow S down the middle
  ROWS.forEach(([ry, hw, xo], j) => {
    const beat = (j + f) % 3;                                        // striations travel UP the roll frame to
    const tat = (j + f) & 1;                                         // frame: the read that the whole thing
    const y = gy - ry;                                               // spins — and the silhouette TATTERS, each
    const x0 = cx + xo - hw + tat, xR = cx + xo + hw - tat;          // edge pulling in a pixel on its own beat
    const gp = cx + xo + THROAT[(j + f * 2) % THROAT.length];        // a TORN GAP spirals through the roll —
    const body = j < 10 ? GALE.shade : GALE.base;                    // the road shows through a storm, which is
    p.px(x0, y, gp - x0, 1, body);                                   // what keeps it weather and not a boulder
    p.px(gp + 2, y, xR - gp - 2, 1, body);                           // (and the crest rows thin to paler dust)
    p.px(gp + 2, y, 1, 1, GALE.line);                                // the tear's inner edge falls into shadow
    if (beat !== 1 && j < 10) {                                      // two bands in three carry the paler dust…
      const ins = beat === 0 ? 2 : 4;
      p.px(x0 + ins, y, gp - x0 - ins, 1, GALE.base);
      p.px(gp + 3, y, xR - gp - 3, 1, GALE.base);
    }
    if (beat === 0) p.px(cx + xo + LS[j], y, 3, 1, GALE.light);      // …one hard lit rim walks the band,
    if (beat === 2 && j < 10) p.px(xR - 3, y, 2, 1, GALE.light);     // …and the trailing rim answers it
    if (beat === 1) p.px(x0 - 2, y, 1, 1, GALE.shade);               // dust flying off the leading edge
  });
  p.px(cx - 12 - f, gy - 15, 2, 1, GALE.base);                       // spray ripped off the crest tip
  for (let i = 0; i < 4; i++)                                        // wisps torn off the crown: LOOSE motes
    p.px(cx - 10 + i * 3, gy - 15 - ((f + i * 2) % 3), 1, 1, GALE.base); // on their own beats — a dithered
  for (let i = 0; i < 3; i++)                                        // band up here reads as battlements, and
    p.px(cx - 9 + i * 5, gy - 17 - ((f + i) % 3), 1, 1, GALE.shade); // a dashed box reads as UI
  const LEAF = [[-11, 4], [-8, 13], [-1, 15], [8, 12], [12, 6], [4, 2]]; // perimeter stations for the debris
  for (let i = 0; i < 3; i++) {
    const [lx, ly] = LEAF[(i * 2 + f) % LEAF.length];                // each leaf hops one station per frame:
    p.px(cx + lx, gy - ly, 1, 1, i === 1 ? "#6d8a3a" : WOOD.light);  // orbiting, not twinkling
  }
  const [tx, ty2] = LEAF[(3 + f) % LEAF.length];                     // a snapped twig rides the same orbit,
  p.px(cx + tx, gy - ty2 + 1, 2, 1, WOOD.shade);                     // half a beat behind the leaves
  if (d2()) { p.px(cx - 9, gy - 3, 1, 1, GALE.light); p.px(cx + 7, gy - 11, 1, 1, GALE.light); } // fine spray
                                                                     // glints on the flanks at fine scales
}

function propIdol(p, f) { // a squat carved watcher on a plinth: the stone is ancient, the eyes are not
  const gy = MON_FOOT_Y, cx = MON_CX;
  const slab = (wd, yy, hh) => {                                     // the shrine's masonry, restated — the
    p.px(cx - (wd >> 1) - 1, yy - 1, wd + 2, hh + 1, STONE.line);    // two monuments must read as one quarry
    p.px(cx - (wd >> 1), yy, wd, hh, STONE.base);
    p.px(cx - (wd >> 1), yy, wd, 1, STONE.light);
    p.px(cx - (wd >> 1), yy, 1, hh, STONE.light);
    p.px(cx + (wd >> 1) - 1, yy, 1, hh, STONE.shade);
  };
  slab(16, gy - 1, 2);                                               // ground step
  slab(13, gy - 4, 3);                                               // plinth
  slab(12, gy - 11, 7);                                              // the folded body…
  slab(10, gy - 17, 2);                                              // …under a head it never grew a neck for:
  slab(12, gy - 15, 4);                                              // crown narrow, cheeks wide — a stepped
                                                                     // dome, whose border row IS the heavy brow
  p.px(cx - 9, gy - 15, 2, 3, STONE.line);                           // carved side flanges — ears on a thing
  p.px(cx - 9, gy - 15, 2, 2, STONE.base);                           // that only ever listens
  p.px(cx - 9, gy - 15, 1, 1, STONE.light);
  p.px(cx + 7, gy - 15, 2, 3, STONE.line);
  p.px(cx + 7, gy - 15, 2, 2, STONE.base);
  p.px(cx + 8, gy - 15, 1, 2, STONE.shade);
  p.px(cx - 2, gy - 19, 4, 2, STONE.line);                           // a squat stone topknot
  p.px(cx - 1, gy - 19, 2, 1, STONE.base);
  p.px(cx - 1, gy - 19, 1, 1, STONE.light);
  for (let i = 0; i < 2; i++) p.px(cx - 3 + i * 6, gy - 17, 1, 1, STONE.shade); // the crown's light row
                                                                     // notched twice: weathered, not cut
  const ecol = [FIRE.base, FIRE.light, FIRE.shade][f];               // the pulse: waking, blazing, banked
  for (const ex of [cx - 4, cx + 2]) {
    p.px(ex - 1, gy - 15, 4, 2, STONE.line);                         // socket, carved up under the brow
    p.px(ex, gy - 14, 2, 1, ecol);                                   // the amber gem is a lit SLIT, not a lamp
    if (f === 1) {                                                   // at the peak of the pulse the glow leaks
      p.px(ex - 1, gy - 14, 1, 1, FIRE.shade);                       // past both corners of the socket…
      p.px(ex + 2, gy - 14, 1, 1, FIRE.shade);
      p.px(ex, gy - 13, 2, 1, FIRE.shade);                           // …and spills down onto the cheek
    }
  }
  p.px(cx - 1, gy - 15, 2, 3, STONE.base);                           // the nose ridge between the sockets,
  p.px(cx - 1, gy - 15, 1, 3, STONE.light);                          // catching what light gets under the brow
  p.px(cx - 1, gy - 12, 2, 1, STONE.shade);                          // and throwing its little shadow
  p.px(cx - 3, gy - 12, 2, 1, STONE.line);                           // the mouth: a grimace of carved teeth,
  p.px(cx + 1, gy - 12, 3, 1, STONE.line);                           // split by the nose shadow
  for (let i = 0; i < 3; i++) p.px(cx - 3 + i * 3, gy - 11, 1, 1, STONE.line); // teeth hanging off the slot —
                                                                     // it has not liked anything for centuries
  p.px(cx - 5, gy - 9, 10, 1, STONE.shade);                          // arms folded across the belly, one groove
  p.px(cx - 1, gy - 8, 2, 1, STONE.shade);                           // hands stacked beneath them
  if (f === 1) p.px(cx, gy - 7, 1, 1, FIRE.shade);                   // a belly rune that only shows when the
                                                                     // eyes blaze: the glow is INSIDE the stone
  p.px(cx - 4, gy - 6, 1, 2, STONE.shade);                           // crossed legs carved into the base,
  p.px(cx + 3, gy - 6, 1, 2, STONE.shade);                           // two short grooves
  p.px(cx + 4, gy - 10, 1, 2, STONE.shade);                          // a crack down the shoulder…
  p.px(cx - 3, gy - 3, 2, 1, STONE.shade);                           // …and one on the plinth: old masonry
  p.px(cx - 5, gy - 12, 1, 1, "#4f7a3a");                            // moss in the neck seam
  p.px(cx + 4, gy - 2, 1, 1, "#4f7a3a");                             // moss on the plinth
  if (d2()) { p.px(cx + 6, gy - 13, 1, 1, "#4f7a3a"); p.px(cx - 7, gy - 1, 1, 1, "#4f7a3a"); } // more moss
                                                                     // creeping in at fine scales
  const bx = cx - 13;                                                // the offering bowl at its feet, set
  p.px(bx - 1, gy - 2, 7, 3, STONE.line);                            // toward the road it watches
  p.px(bx, gy - 2, 5, 1, STONE.base);
  p.px(bx, gy - 2, 1, 1, STONE.light);
  p.px(bx + 1, gy - 1, 3, 1, FIRE.shade);                            // an ember bed — someone still feeds it
  if (f === 2) p.px(bx + 2, gy - 1, 1, 1, FIRE.base);                // …and it answers the eyes on the off-beat
  p.px(bx + 2 + (f & 1), gy - 4 - f, 1, 1, "#4a4550");               // one thread of smoke, climbing
  if (d2()) p.px(bx + 6, gy, 1, 1, GOLD.base);                       // a dropped coin at fine scales
}

/**
 * Draw one prop with its TOP-LEFT CORNER at (x, y) — same convention and the same PROP_W × PROP_H
 * (= MON_W × MON_H) box as drawMonster, so the world renderer converts ground coordinates once and uses it
 * for every tile.
 * opts = { kind: "hazard"|"cache"|"shrine"|"forge"|"relic"|"fork"|"gale"|"idol" (or its index in PROP_KINDS),
 *          frame: int — flame flicker / lid breath / gem pulse, cycle length 3 (frame % 3 is enough),
 *          scale: int ≥ 1, facing: 1|-1 (only the fork really cares) }
 * Deterministic: nothing here reads a clock.
 */
export function drawProp(ctx, x, y, opts = {}) {
  DETAIL = opts.detail === 2 ? 2 : 1;
  const kind = typeof opts.kind === "number" ? PROP_KINDS[opts.kind] : opts.kind;
  const scale = Math.max(1, opts.scale | 0 || 1);
  const f = Math.max(0, opts.frame | 0) % 3;
  ctx.imageSmoothingEnabled = false;
  const p = pen(ctx, x, y, scale, opts.facing === -1 ? -1 : 1, false, null, PROP_W, PROP_H);
  switch (kind) {
    case "hazard": propHazard(p, f); break;
    case "cache":  propCache(p, f);  break;
    case "shrine": propShrine(p, f); break;
    case "forge":  propForge(p, f);  break;
    case "relic":  propRelic(p, f);  break;
    case "fork":   propFork(p, f);   break;
    case "gale":   propGale(p, f);   break;
    case "idol":   propIdol(p, f);   break;
    default: return { w: MON_W_N * scale, h: MON_H_N * scale }; // unknown kind draws NOTHING rather than a
                                                                // wrong thing — the caller keeps its fallback
  }
  return { w: MON_W_N * scale, h: MON_H_N * scale };
}

// ══ BLOOD ════════════════════════════════════════════════════════════════════════════════
// Every fight leaves a mark. This is a separate layer rather than something baked into the monster art
// because the renderer needs to put blood on BOTH sides of a swing, keep a pool under a corpse for the rest
// of the chapter, and lay dried splatter on road the player has already walked.
//
// Determinism is not optional here: the whole game replays from two block hashes, so a splatter has to be a
// pure function of (seed, kind, frame, amount). `seed` is the caller's — a step index, a run id, anything —
// and is run through an integer hash so consecutive seeds do not produce near-identical sprays.
const BLOOD_W = MON_W;
const BLOOD_H = MON_H;
export { MON_W_N as BLOOD_W, MON_H_N as BLOOD_H };
export const BLOOD_KINDS = ["hit", "spurt", "pool", "splatter", "gib", "mist"];
// frames per kind; a caller that runs past the end just gets the last frame (spray gone, pool full grown)
export const BLOOD_FRAMES = { hit: 5, spurt: 7, pool: 6, splatter: 1, gib: 8, mist: 6 };

// One ramp, shaped like a MATERIAL, so blood shades with the same four stops as everything else. Arterial
// red is deliberately dark at the base and hot only on the lit edge — a flat bright red on a pixel grid
// reads as a UI element, not as fluid.
const BLOOD_RED = { base: "#a01020", shade: "#5e0a14", light: "#e0303c", line: "#2a040a" };
const BLOOD_DRY = { base: "#5a1a1c", shade: "#3a1012", light: "#7a2a26", line: "#1a0708" };
const GORE      = { base: "#8c2b3a", shade: "#54121d", light: "#c05464", line: "#250509" }; // meat/entrails

/** integer hash — the deterministic stand-in for Math.random, which must never appear in this file */
function hash32(n) {
  let a = (n | 0) ^ 0x9e3779b9;
  a = (a ^ (a >>> 16)) | 0;
  a = Math.imul(a, 0x21f0aaad);
  a = (a ^ (a >>> 15)) | 0;
  a = Math.imul(a, 0x735a2d97);
  return ((a ^ (a >>> 15)) >>> 0);
}

/** the layer itself, against an already-configured pen — so the corpse and fatality code can bleed into
 *  their own frame without a second canvas. o = { frame, amount, seed, cx, cy } in frame-local pixels. */
function drawBloodInto(p, kind, o = {}) {
  // clamped, not wrapped: a caller that keeps counting past the end gets the settled state (spray landed,
  // pool full) instead of droplets sailing off the top of the frame forever
  const f = Math.max(0, Math.min((BLOOD_FRAMES[kind] || 1) - 1, o.frame | 0));
  const amount = Math.max(1, o.amount | 0 || 1);
  const seed = o.seed | 0;
  const cx = o.cx == null ? MON_CX : o.cx | 0;
  const gy = MON_GROUND_Y;

  if (kind === "pool") { // grows for BLOOD_FRAMES.pool frames, then holds: a corpse keeps bleeding a while
    const g = Math.min(BLOOD_FRAMES.pool - 1, f);
    const w = Math.min(34, 5 + amount + g * 3);
    const h = Math.max(2, 2 + (g >> 1) + (amount > 8 ? 1 : 0));
    const x = cx - (w >> 1), y = gy - h + 1;
    for (const [rx, ry, rw] of rowsOf(x, y, w, h, 1)) {
      p.raw(rx - 1, ry, rw + 2, 1, BLOOD_RED.line);
      p.raw(rx, ry, rw, 1, ry === y ? BLOOD_RED.base : BLOOD_RED.shade);
    }
    p.raw(x + 2, y, Math.max(1, w >> 2), 1, BLOOD_RED.light);       // the one specular streak
    p.dither(x - 2, y - 1, w + 4, h + 1, BLOOD_RED.shade, g & 1);   // ragged edge, dither instead of alpha
    return;
  }

  if (kind === "splatter") { // dried, static, laid down once — this is road you have already fought over
    const n = Math.min(40, 6 + amount * 3);
    for (let i = 0; i < n; i++) {
      const r = hash32(seed * 2654435761 + i);
      const dx = ((r % 31) | 0) - 15;
      const dy = ((r >> 6) % 3) | 0;
      const big = ((r >> 11) & 7) === 0;
      p.raw(cx + dx, gy - dy, big ? 2 : 1, 1, big ? BLOOD_DRY.base : BLOOD_DRY.shade);
      if (big) p.raw(cx + dx, gy - dy, 1, 1, BLOOD_DRY.light);
    }
    return;
  }

  if (kind === "mist") { // a fine arterial cloud that BLOOMS out of the wound and thins as it drifts up —
    // the after-image of a killing blow. Density falls with the frame so it fades without any alpha channel.
    const cy = o.cy == null ? MON_FOOT_Y - 13 : o.cy | 0;
    const spread = 4 + f * 4;                         // widens every frame
    const rise = f * 2;                               // and lifts
    const density = Math.max(1, 4 - (f >> 1));        // 1 in `density` pixels lit — thins as it disperses
    const n = Math.min(90, 20 + amount * 4);
    for (let i = 0; i < n; i++) {
      const r = hash32(seed * 0x9e3779b1 + i * 131 + 51);
      if ((r % density) !== 0) continue;
      const ang = (r >> 4) % 360;
      const rad = (r >> 9) % spread;
      const dx = (((r & 1) ? 1 : -1) * ((ang * rad) % (spread + 1))) % (spread + 3);
      const dy = -((rad >> 1)) - rise + (((r >> 12) & 1));
      const px0 = cx + dx, py = cy + dy;
      if (py < 0 || py >= MON_FOOT_Y) continue;
      const hot = (r >> 3) & 3;
      p.px(px0, py, 1, 1, hot === 0 ? BLOOD_RED.light : hot === 1 ? GORE.base : BLOOD_RED.base);
    }
    return;
  }

  if (kind === "gib") { // CHUNKS. Meat and bone torn loose on a heavy kill: fat 2×2/3×2 gobbets that arc
    // out, TUMBLE (they flip colour every frame so they read as spinning), fall under the same integer
    // gravity as a droplet, and SLAP down into a lasting smear. This is the "absolutely brutal" layer.
    const cy = o.cy == null ? MON_FOOT_Y - 12 : o.cy | 0;
    const n = Math.min(18, 4 + amount);
    for (let i = 0; i < n; i++) {
      const r = hash32(seed * 2246822519 + i * 61 + 13);
      const back = ((r >> 2) & 3) === 0;
      const vx = (2 + (r % 4)) * (back ? -1 : 1);
      const vy = -2 - ((r >> 5) % 3);
      const t = f - (((r >> 8) % 2) | 0);
      if (t < 0) continue;
      const dx = vx * t, dy = vy * t + ((t * (t + 1)) >> 1);
      const gx0 = cx + dx, gyp = cy + dy;
      const big = (r >> 11) & 1;                       // some bone-white, most meat
      const bw = big ? 3 : 2, bh = 2;
      if (gyp >= MON_FOOT_Y) {                         // landed: a torn smear that stays on the road
        p.raw(gx0 - 1, gy, bw + 1, 1, GORE.shade);
        p.raw(gx0, gy, bw, 1, GORE.base);
        if (big) p.px(gx0, gy, 1, 1, BLOOD_RED.light);
        continue;
      }
      const tumble = (t & 1);                          // flip lit/shade each frame → it spins
      p.raw(gx0 - 1, gyp, bw + 2, bh, GORE.line);      // dark outline so a chunk reads against a monster
      p.raw(gx0, gyp, bw, bh, tumble ? GORE.base : GORE.shade);
      p.px(gx0 + (tumble ? 0 : bw - 1), gyp, 1, 1, big ? "#d8c4b0" : GORE.light); // bone glint / wet highlight
      // a thin blood tail off the trailing edge — a chunk with a streak reads as flung, not floating
      p.px(gx0 - Math.sign(vx), gyp + 1, 1, 1, BLOOD_RED.shade);
    }
    if (f >= 2) drawBloodInto(p, "mist", { frame: f - 2, amount: (amount >> 1) + 1, seed: seed ^ 0x5bd1, cx, cy });
    return;
  }

  // "hit" and "spurt" are the same ballistics with different volume: droplets launched from one point and
  // pulled down by an integer gravity, so frame N is a POSITION, not a random re-roll. A droplet that
  // reaches the ground stops being a droplet and becomes a mark, which is what makes the road accumulate.
  const heavy = kind === "spurt";
  const cy = o.cy == null ? MON_FOOT_Y - 12 : o.cy | 0;
  const n = Math.min(heavy ? 52 : 34, (heavy ? 14 : 8) + amount * (heavy ? 3 : 2));
  const life = heavy ? BLOOD_FRAMES.spurt : BLOOD_FRAMES.hit;
  if (f === 0) { // the impact itself: a hard star, one frame only. Without it the spray has no cause.
    p.px(cx - 3, cy, 7, 1, BLOOD_RED.light);
    p.px(cx, cy - 3, 1, 7, BLOOD_RED.light);
    p.px(cx - 1, cy - 1, 3, 3, BLOOD_RED.base);
  }
  for (let i = 0; i < n; i++) {
    const r = hash32(seed * 40503 + i * 97 + (heavy ? 7919 : 0));
    const back = ((r >> 3) & 3) === 0;              // a quarter of it sprays back past the swing
    const vx = (1 + (r % (heavy ? 4 : 3))) * (back ? -1 : 1);
    const vy = -1 - ((r >> 5) % 3);                 // kept low on purpose: a wide slow scatter reads as
                                                    // confetti, a tight fast one reads as blood
    const t = f - (((r >> 9) % 2) | 0);             // stagger the launch by a frame so it is not one wall
    if (t < 0) continue;
    const dx = vx * t, dy = vy * t + ((t * (t + 1)) >> 1); // integer parabola: v*t + t(t+1)/2
    const px0 = cx + dx, py = cy + dy;
    if (py >= MON_FOOT_Y) { p.raw(px0, gy, 1 + (i & 1), 1, BLOOD_RED.shade); continue; } // landed: a mark
    const big = heavy && (i & 3) === 0;
    // a droplet plus the pixel it was at last frame: a bead with a tail reads as flying, a loose bead
    // reads as confetti
    p.px(px0 - Math.sign(vx), py - vy - t + 1, 1, 1, BLOOD_RED.shade);
    p.px(px0, py, big ? 2 : 1, big ? 2 : 1, t > 2 ? BLOOD_RED.base : BLOOD_RED.light);
  }
  if (heavy) { // the jet: three arcs of beads out of the wound, lengthening while the heart still works
    for (let j = 0; j < 3; j++) {
      const len = Math.min(10, 3 + f * 2 - j);
      for (let i = 0; i < len; i++) { // out of the wound, UP first and then falling: the arc is the read
        const bx = cx - i * 2 - j, by = cy - i - j + (((i + j) * (i + j)) / 3 | 0);
        if (by >= MON_FOOT_Y) { p.raw(bx, MON_GROUND_Y, 2, 1, BLOOD_RED.shade); continue; }
        p.px(bx, by, 2, 1, i < 3 ? BLOOD_RED.light : BLOOD_RED.base);
      }
    }
    if (f >= 3) drawBloodInto(p, "pool", { frame: f - 3, amount, seed, cx });
  } else if (f >= life - 2) {
    p.dither(cx - 6, gy - 2, 13, 3, BLOOD_RED.shade, f & 1);        // the last of it hitting the dirt
  }
}

/**
 * Blood, with its TOP-LEFT CORNER at (x, y) in a BLOOD_W × BLOOD_H box that matches the monster/prop box —
 * the ground line is row MON_GROUND_Y, the same one the sprites stand on, so a caller that already places
 * monsters places blood with the identical maths.
 *
 * opts = {
 *   kind:   "hit"     — a blow lands: burst star + a spray that ARCS AND FALLS   (frames 0..4)
 *           "spurt"   — arterial, for a kill: heavier spray + jet + a pool forms (frames 0..6)
 *           "pool"    — a puddle that GROWS under a corpse and then holds        (frames 0..5)
 *           "splatter"— dried marks left on ground already fought over           (static, frame ignored)
 *   frame:  int, clamped to the kind's length (see BLOOD_FRAMES)
 *   amount: int ≥ 1 — volume. A 16-foe pull should pass ~16 and visibly bleed more than a lone grunt.
 *   seed:   int — same seed ⇒ same splatter, forever. Derive it from the step/run so a replay matches.
 *   scale:  int ≥ 1, facing: 1|-1 (mirrors the spray direction)
 *   cx, cy: optional wound position in frame pixels (defaults: centre, chest height)
 * }
 * Returns { w, h } in device pixels.
 */
export function drawBlood(ctx, x, y, opts = {}) {
  const kind = typeof opts.kind === "number" ? BLOOD_KINDS[opts.kind] : (opts.kind || "hit");
  if (!BLOOD_KINDS.includes(kind)) return { w: 0, h: 0 };
  const scale = Math.max(1, opts.scale | 0 || 1);
  ctx.imageSmoothingEnabled = false;
  const p = pen(ctx, x, y, scale, opts.facing === -1 ? -1 : 1, false, null, BLOOD_W, BLOOD_H);
  // public cx/cy are NATIVE frame pixels (the exported box); the painter itself works on the authored grid
  drawBloodInto(p, kind, {
    ...opts,
    cx: opts.cx == null ? null : Math.round(opts.cx / HR),
    cy: opts.cy == null ? null : Math.round(opts.cy / HR),
  });
  return { w: MON_W_N * scale, h: MON_H_N * scale };
}

// ══ FATALITIES ═══════════════════════════════════════════════════════════════════════════
// When the hero dies the chapter is over, so the death gets the budget: six Mortal-Kombat-style finishers,
// picked deterministically by the caller (`which`) from the run, so a given death always replays identically.
//
// These are NOT effects pasted over a corpse. Each one re-uses the SAME gear-composed warrior painter as
// drawWarrior, through a pen that is offset and CLIPPED to a body part — so a decapitated head is still
// wearing your tier-7 helm, the severed arm is still holding your sword, and the ash pile still has your
// gold cuirass in it. Throwing the build away at the moment of death would throw away the whole point of
// composing the sprite from the build.
//
// Frame convention: frames run 0 → frames-1 for the fatality you selected; the LAST frame is the resting
// corpse and is safe to hold indefinitely. Frames past the end clamp to it.
const FAT_W = MON_W;
const FAT_H = MON_H;
export { MON_W_N as FAT_W, MON_H_N as FAT_H };
const FAT_DX = 9, FAT_DY = 15; // where the 32×32 warrior cell sits inside the 48×48 gore frame: this maps
                               // his FOOT_Y/GROUND_Y onto MON_FOOT_Y/MON_GROUND_Y and his CX onto MON_CX,
                               // so warrior art, monster art and blood all share one ground line.
export const FATALITIES = [
  { name: "decapitation", frames: 8 }, // 0 head off, fountain, body folds
  { name: "bisection",    frames: 8 }, // 1 cut at the waist, top half slides off
  { name: "impalement",   frames: 9 }, // 2 spike erupts, body rides it down
  { name: "immolation",   frames: 9 }, // 3 burns to a skeleton, then to ash
  { name: "dismember",    frames: 8 }, // 4 torn apart, limbs thrown
  { name: "crushed",      frames: 8 }, // 5 flattened from above
];

// body-part row bands in the warrior's authored coordinates (head 5-11, torso 12-20, legs 21-31)
const CLIP_HEAD = { y0: 0, y1: 11 };
const CLIP_TOP = { y0: 0, y1: 20 };
const CLIP_TORSO = { y0: 12, y1: 20 };
const CLIP_LEGS = { y0: 21, y1: 31 };
const CHAR = (c) => mix(c, "#1b1216", 0.72);   // burnt
const COLD = (c) => mix(c, "#2b2430", 0.45);   // dead (the same map drawWarrior uses)
const HELM_ONLY = (gear) => [0, gear[1] | 0, 0, 0, 0, 0]; // paint just the head+helm through the clip
const WEAP_ONLY = (gear) => [gear[0] | 0, 0, 0, 0, 0, 0];

/** one warrior part: the shared painter, offset by (dx,dy) and clipped to a body band. `dx` is mirrored with
 *  facing so a head thrown "forward" goes forward whichever way the hero faces. */
// A part drawn ROTATED lands on its side: the pen's 90° remap puts it in sub-frame rows ~19..32, so it has
// to be lifted, or the bottom of the gore frame eats it and the fallen half ends up half-buried in the road.
const FAT_ROT_LIFT = -3;

function fatPart(ctx, x, y, scale, facing, gear, ps, frame, dx, dy, clip, recolor, rot) {
  const ox = FAT_DX + (facing < 0 ? -dx : dx), oy = FAT_DY + dy + (rot ? FAT_ROT_LIFT : 0);
  const bound = {
    x0: Math.max(0, -ox), y0: Math.max(0, -oy),
    x1: Math.min(FRAME_W, FAT_W - ox), y1: Math.min(FRAME_H, FAT_H - oy),
  };
  // ox/oy are authored offsets inside the gore frame → HR native px each → HR*scale device px
  const p = pen(ctx, x + ox * HR * scale, y + oy * HR * scale, scale, facing, !!rot, recolor || null,
                FRAME_W, FRAME_H, clip || null, bound);
  paintWarrior(p, gear, ps, frame, facing);
}

const STAND = POSES.walk[0];
const SLUMP = POSES.walk[1];
const LUNGE = POSES.attack[2];

/** a bone pile / skeleton, authored: at 24 px a "skeleton" is a skull, a ribcage and two sticks */
function skeleton(p, x, y, ribs = 4) {
  const B = { base: "#e8e2cc", shade: "#a89f84", light: "#ffffff", line: "#3a3423" };
  mass(p, x, y, 7, 7, B, 1);                       // skull
  p.px(x + 1, y + 2, 2, 2, "#1a1510");             // sockets
  p.px(x + 4, y + 2, 2, 2, "#1a1510");
  p.px(x + 2, y + 5, 3, 1, "#1a1510");             // jaw
  p.px(x + 3, y + 7, 2, 2, B.shade);               // neck
  for (let i = 0; i < ribs; i++) {                 // ribcage, widening down the chest
    const w = 7 + (i < 2 ? i : ribs - 1 - i);
    p.px(x - ((w - 7) >> 1), y + 9 + i * 2, w, 1, B.base);
    p.px(x - ((w - 7) >> 1), y + 9 + i * 2, 1, 1, B.light);
  }
  p.px(x + 3, y + 9, 1, ribs * 2, B.light);        // spine
  if (ribs > 2) {                                  // arm bones hanging off the shoulders
    p.limb(x, y + 9, x - 2, y + 9 + ribs * 2, 1, B.shade);
    p.limb(x + 6, y + 9, x + 8, y + 9 + ribs * 2, 1, B.shade);
  }
}

function fatDecap(ctx, x, y, s, fc, gear, f, gp) {
  // head arc: hand-picked positions, and the head TUMBLES by flipping its own facing every other frame —
  // free rotation for a sprite that has no rotation.
  const HX = [0, 1, 3, 6, 9, 12, 14, 15], HY = [0, -2, -6, -7, -2, 6, 15, 19];
  const body = f < 2 ? STAND : SLUMP;
  const down = f >= 5;                             // from here the body is on the floor
  if (f >= 4) drawBloodInto(gp, "pool", { frame: f - 4, amount: 10, seed: 11, cx: MON_CX });
  // the body is ALWAYS clipped below the neck, standing or fallen: dropping the clip once he is down puts
  // a second (rotated) head on the corpse while the first one is still rolling away
  fatPart(ctx, x, y, s, fc, gear, down ? POSES.dead : body, 0, down ? 2 : 0, down ? 0 : Math.min(3, f - 2),
          { y0: 12, y1: 31 }, down ? COLD : null, down);
  if (!down) { // the stump, and what is coming out of it
    gp.px(MON_CX - 2, FAT_DY + 11, 5, 2, GORE.base);
    gp.px(MON_CX - 2, FAT_DY + 11, 5, 1, GORE.light);
    drawBloodInto(gp, "spurt", { frame: f, amount: 9, seed: 3, cx: MON_CX, cy: FAT_DY + 10 });
  }
  fatPart(ctx, x, y, s, f & 1 ? -fc : fc, gear, STAND, 0, HX[f], HY[f], CLIP_HEAD, f >= 6 ? COLD : null);
  if (f >= 2 && f <= 5) drawBloodInto(gp, "hit", { frame: Math.min(4, f - 2), amount: 4, seed: 5, cx: MON_CX + 4, cy: FAT_DY + 9 });
}

function fatBisect(ctx, x, y, s, fc, gear, f, gp) {
  // The top half has to LAND. Slid sideways and left upright it reads as a man stepping out of his own
  // trousers, so from f4 it goes over onto its side through the pen's rotation — the same 90° remap the
  // warrior's own death pose uses.
  const TX = [0, 0, 2, 4, 5, 6, 6, 6], TY = [0, 0, -1, 1, 2, 3, 3, 3];
  const legDy = [0, 0, 0, 1, 2, 3, 3, 3][f]; // the knees buckle a little; sinking them furtherjust pushes
  const legDown = f >= 5;                    // them through the frame's bottom edge, so from f5 they TOPPLE
  const tDown = f >= 4;
  if (f >= 3) drawBloodInto(gp, "pool", { frame: f - 3, amount: 12, seed: 21, cx: MON_CX + 1 });
  // legs first: they stand a beat on their own, then fold
  fatPart(ctx, x, y, s, fc, gear, legDown ? POSES.dead : f < 3 ? STAND : SLUMP, 0, legDown ? -4 : 0,
          legDown ? 0 : legDy, CLIP_LEGS, f >= 4 ? COLD : null, legDown);
  if (f >= 1) { // the cut: a bright line first, then meat
    gp.px(MON_CX - 4, FAT_DY + 20 + legDy, 9, 1, f === 1 ? "#ffe9a8" : GORE.light);
    gp.px(MON_CX - 4, FAT_DY + 21 + legDy, 9, 1, GORE.shade);
  }
  if (f >= 2) { // entrails spilling out of the standing half — this is the fatality's whole read
    for (let i = 0; i < 6 + f; i++) {
      const r = hash32(31 * i + f);
      gp.px(MON_CX - 4 + (r % 9), FAT_DY + 21 + ((r >> 5) % (2 + f)) + legDy, 2, 1, i & 1 ? GORE.base : GORE.shade);
    }
    drawBloodInto(gp, "spurt", { frame: Math.min(6, f), amount: 12, seed: 9, cx: MON_CX, cy: FAT_DY + 20 });
  }
  fatPart(ctx, x, y, s, fc, gear, f < 3 ? STAND : LUNGE, 0, TX[f], tDown ? 0 : TY[f], CLIP_TOP,
          f >= 5 ? COLD : null, tDown);
  if (tDown) { // the sawn edge of the half now lying on the ground
    gp.px(MON_CX + 2, MON_FOOT_Y - 3, 6, 3, GORE.shade);
    gp.px(MON_CX + 2, MON_FOOT_Y - 3, 6, 1, GORE.light);
  }
}

function fatImpale(ctx, x, y, s, fc, gear, f, gp) {
  const grow = [0, 4, 12, 20, 26, 26, 26, 26, 26][f]; // tall enough to come out ABOVE the shoulders
  const bodyDy = [0, 0, -3, -5, -4, -2, 0, 1, 1][f];
  if (f >= 1) { // the shaft: a tapered stone spike, drawn behind the body so the body sits ON it
    const top = MON_FOOT_Y - grow;
    for (let i = 0; i < grow; i++) {
      const w = 1 + ((i / 5) | 0);
      gp.px(MON_CX - 1 - (w >> 1), top + i, w + 2, 1, STONE.line);
      gp.px(MON_CX - (w >> 1), top + i, w, 1, STONE.base);
      gp.px(MON_CX - (w >> 1), top + i, 1, 1, STONE.light);
    }
    horn(gp, MON_CX, top, 0, -1, 3, STONE);
    for (let i = 2; i < grow - 2; i += 2) gp.px(MON_CX, top + i + (f & 1), 1, 2, BLOOD_RED.base); // runs down
  }
  fatPart(ctx, x, y, s, fc, gear, f < 2 ? STAND : SLUMP, 0, 0, bodyDy, null, f >= 5 ? COLD : null);
  if (f >= 2) { // re-draw the length of shaft that is IN FRONT of him: a spike hidden entirely behind the
    const top = MON_FOOT_Y - grow;                 // body is just a man crouching in a puddle
    for (let i = 0; i < 9; i++) {
      gp.px(MON_CX - 2, top + i, 4, 1, STONE.line);
      gp.px(MON_CX - 1, top + i, 2, 1, STONE.base);
      gp.px(MON_CX - 1, top + i, 1, 1, STONE.light);
      if (i > 2) gp.px(MON_CX - 1, top + i + (f & 1), 1, 2, BLOOD_RED.base);
    }
    horn(gp, MON_CX, top, 0, -1, 4, STONE);
  }
  if (f >= 2) {
    gp.px(MON_CX - 2, FAT_DY + 14 + bodyDy, 4, 3, GORE.base);   // where it came through
    gp.px(MON_CX - 2, FAT_DY + 14 + bodyDy, 4, 1, GORE.light);
    drawBloodInto(gp, "spurt", { frame: Math.min(6, f - 1), amount: 10, seed: 41, cx: MON_CX, cy: FAT_DY + 15 + bodyDy });
  }
  if (f >= 5) drawBloodInto(gp, "pool", { frame: f - 5, amount: 11, seed: 41, cx: MON_CX });
}

function fatBurn(ctx, x, y, s, fc, gear, f, gp) {
  // Flames are TONGUES with a hot core, licking up the body's own outline. A dithered orange rectangle laid
  // over him reads as a checkerboard curtain hung in front of the sprite — the exact failure this file's
  // no-alpha rule exists to avoid.
  const lick = (x0, w, base, height, seed) => {
    for (let i = 0; i < w; i++) {
      const t = FLAME[(i + f * 3 + seed) % FLAME.length] + height;
      if (t <= 0) continue;
      gp.px(x0 + i, base - t, 1, t, FIRE.shade);
      gp.px(x0 + i, base - t, 1, (t >> 1) + 1, FIRE.base);
      gp.px(x0 + i, base - t, 1, 1, FIRE.light);
    }
  };
  if (f <= 4) { // burning: he chars through the recolour while the fire climbs him. The pyre is drawn
    // BEHIND him and only every third column licks over the front, or the fire becomes an orange wall with
    // a man somewhere behind it — which is not a death, it is a rectangle.
    lick(MON_CX - 8, 17, MON_FOOT_Y, 1 + f * 2, 0);
    fatPart(ctx, x, y, s, fc, gear, f < 2 ? STAND : SLUMP, 0, 0, f < 2 ? 0 : 1, null, f < 2 ? null : CHAR);
    for (let i = 0; i < 6; i++) {                               // tongues in front, spaced out
      const cxx = MON_CX - 7 + i * 3, t = 2 + FLAME[(i + f * 2) % FLAME.length] + f;
      gp.px(cxx, MON_FOOT_Y - 6 - t, 1, t, FIRE.base);
      gp.px(cxx, MON_FOOT_Y - 6 - t, 1, 1, FIRE.light);
    }
    if (f >= 3) lick(MON_CX - 6, 13, MON_FOOT_Y - 24, 1, 7);    // and finally over his head
  } else if (f <= 6) { // the flesh is gone: a skeleton in your helmet, still standing for one beat
    skeleton(gp, MON_CX - 4, FAT_DY + 8, 5);
    fatPart(ctx, x, y, s, fc, HELM_ONLY(gear), STAND, 0, 0, 3, CLIP_HEAD, CHAR);
    lick(MON_CX - 7, 15, MON_FOOT_Y, 6 - (f - 5) * 2, 3);
  } else { // ash: a mound with the gear still in it, and embers that will not quite go out
    const w = 19, h = 5;
    for (const [rx, ry, rw] of rowsOf(MON_CX - (w >> 1), MON_FOOT_Y - h + 1, w, h, 2)) {
      gp.px(rx - 1, ry, rw + 2, 1, "#221c22");
      gp.px(rx, ry, rw, 1, "#3a3038");
      gp.px(rx, ry, 1, 1, "#524650");
    }
    skeleton(gp, MON_CX - 4, MON_FOOT_Y - 9, 1);                // a skull and one rib out of the ash
    fatPart(ctx, x, y, s, fc, HELM_ONLY(gear), STAND, 0, 5, 19, CLIP_HEAD, CHAR); // helm, fallen off it
    fatPart(ctx, x, y, s, fc, WEAP_ONLY(gear), POSES.dead, 0, -5, 0, null, CHAR, true); // sword, dropped
    for (let i = 0; i < 7; i++) {
      const r = hash32(i * 7 + f);
      gp.px(MON_CX - 8 + (r % 16), MON_FOOT_Y - 1 - ((r >> 4) % 3), 1, 1, (i + f) & 1 ? FIRE.base : FIRE.light);
      gp.px(MON_CX - 6 + ((r >> 8) % 12), MON_FOOT_Y - 7 - ((r >> 12) % 5) - (f & 1), 1, 1, FIRE.shade);
    }
  }
}

function fatTear(ctx, x, y, s, fc, gear, f, gp) {
  // Everything leaves at once, in different directions: that spread is the read, so the offsets are picked
  // to keep the four pieces from ever overlapping.
  const TX = [0, 0, 2, 4, 6, 7, 8, 8], TY = [0, -1, -4, -6, -3, 2, 0, 0];
  const HX = [0, -1, -4, -7, -9, -11, -12, -13], HY = [0, -1, -4, -5, -2, 4, 14, 19];
  const LX = [0, 0, -1, -2, -3, -4, -4, -4], LY = [0, 0, 1, 2, 4, 6, 7, 7];
  if (f >= 3) {
    drawBloodInto(gp, "pool", { frame: f - 3, amount: 14, seed: 61, cx: MON_CX });
    drawBloodInto(gp, "splatter", { amount: 8, seed: 61 });
  }
  fatPart(ctx, x, y, s, fc, gear, f < 2 ? STAND : SLUMP, 0, LX[f], LY[f], CLIP_LEGS, f >= 4 ? COLD : null);
  fatPart(ctx, x, y, s, fc, gear, f < 2 ? STAND : LUNGE, 0, TX[f], TY[f], CLIP_TORSO,
          f >= 5 ? COLD : null, f >= 6);
  fatPart(ctx, x, y, s, f & 1 ? -fc : fc, gear, STAND, 0, HX[f], HY[f], CLIP_HEAD, f >= 6 ? COLD : null);
  if (f >= 1) { // the two arms, authored: they are the only pieces the warrior sprite has no clip band for
    for (let k = 0; k < 2; k++) { // ARMS, not blocks: a 3×2 rect flying through the air reads as a crate,
      const ax = MON_CX + (k ? -6 - f * 2 : 5 + f), ay = FAT_DY + 13 - (k ? f : f * 2) + ((f * f) >> 2);
      const tx = ax + (k ? -4 : 4), ty = ay + (k ? 3 : -2);   // each spins off on its own line
      gp.limb(ax - 1, ay - 1, tx - 1, ty - 1, 4, SKIN.line);
      gp.limb(ax, ay, tx, ty, 2, SKIN.base);
      gp.limb(ax, ay, tx, ty, 1, SKIN.light);
      gp.px(tx - 1, ty - 1, 3, 3, SKIN.line);                 // the fist on the end of it
      gp.px(tx, ty, 2, 2, SKIN.base);
      gp.px(ax, ay, 2, 2, GORE.base);                         // and the torn shoulder end
    }
    drawBloodInto(gp, "spurt", { frame: Math.min(6, f), amount: 11, seed: 61, cx: MON_CX, cy: FAT_DY + 14 });
    drawBloodInto(gp, "hit", { frame: Math.min(4, f), amount: 5, seed: 62, cx: MON_CX + 3, cy: FAT_DY + 10 });
  }
}

function fatCrush(ctx, x, y, s, fc, gear, f, gp) {
  const BLOCK_Y = [-22, -16, -8, 2, 2, 0, -6, -18][f]; // descend, land, sit, lift away
  const bw = 26, bx = MON_CX - (bw >> 1), by = MON_FOOT_Y - 15 + BLOCK_Y;
  if (f <= 2) { // he is still alive under a shadow that is getting bigger — the beat before the joke lands
    fatPart(ctx, x, y, s, fc, gear, f === 0 ? STAND : SLUMP, 0, 0, 0, null, null);
    // the shadow of the thing above him, spreading. Two rows of checkerboard read as shade; four read as a
    // texture swatch lying on the road.
    gp.dither(MON_CX - 8 - f * 2, MON_GROUND_Y - 1, 17 + f * 4, 2, "#0d0a12", f & 1);
  }
  if (f === 3) { // impact: blood leaves sideways, because there is nowhere else for it to go
    drawBloodInto(gp, "hit", { frame: 1, amount: 18, seed: 71, cx: MON_CX - 10, cy: MON_FOOT_Y - 2 });
    drawBloodInto(gp, "hit", { frame: 1, amount: 18, seed: 72, cx: MON_CX + 10, cy: MON_FOOT_Y - 2 });
  }
  if (f >= 3) { // the splat, and the gear that survived the man
    drawBloodInto(gp, "pool", { frame: f - 3, amount: 20, seed: 71, cx: MON_CX });
    drawBloodInto(gp, "splatter", { amount: 12, seed: 73 });
    for (const [rx, ry, rw] of rowsOf(MON_CX - 9, MON_FOOT_Y - 2, 19, 3, 1)) {
      gp.px(rx, ry, rw, 1, GORE.shade);
      gp.px(rx, ry, 1, 1, GORE.base);
    }
    if (f >= 5) {
      fatPart(ctx, x, y, s, fc, HELM_ONLY(gear), STAND, 0, -5, 19, CLIP_HEAD, COLD);
      fatPart(ctx, x, y, s, fc, WEAP_ONLY(gear), POSES.dead, 0, 3, 0, null, COLD, true);
    }
  }
  if (BLOCK_Y > -22) { // the slab itself: studded stone, drawn last so it covers whatever it landed on
    for (let j = 0; j < 15; j++) {                 // a squared block with a chipped underside — rounded
      const nick = j > 12 ? ((j * 5 + 3) % 3) : 0; // corners read as a pillow falling on him, not a rock
      gp.px(bx - 1 + nick, by + j, bw + 2 - nick * 2, 1, STONE.line);
      gp.px(bx + nick, by + j, bw - nick * 2, 1, j < 2 ? STONE.light : STONE.base);
      gp.px(bx + nick, by + j, 1, 1, STONE.light);
      gp.px(bx + bw - 1 - nick, by + j, 1, 1, STONE.shade);
      if (j % 4 === 2) gp.px(bx + 3 + j, by + j, 2, 1, STONE.shade); // cracks
    }
    for (let i = 0; i < 4; i++) { // iron studs on its face
      gp.px(bx + 4 + i * 6, by + 4, 2, 2, IRON.base);
      gp.px(bx + 4 + i * 6, by + 4, 2, 1, IRON.light);
      gp.px(bx + 4 + i * 6, by + 10, 2, 2, IRON.shade);
    }
    if (f === 3) for (let i = 0; i < 12; i += 2) gp.raw(MON_CX - 12 + i, MON_GROUND_Y, 2, 1, "#1a1420"); // dust
  }
}

const FAT_FN = [fatDecap, fatBisect, fatImpale, fatBurn, fatTear, fatCrush];

/**
 * Draw one frame of a fatality with its TOP-LEFT CORNER at (x, y) in a FAT_W × FAT_H box — the same box and
 * the same ground row (MON_GROUND_Y) as drawMonster/drawProp/drawBlood, so the world renderer converts
 * ground coordinates exactly once for everything it draws.
 *
 * opts = {
 *   which:  index into FATALITIES (wraps). The CALLER derives it deterministically from the run — e.g.
 *           `hash % FATALITIES.length` off the killing block hash — so a death always replays identically.
 *   frame:  0 … FATALITIES[which].frames-1. The last frame is the resting corpse and may be held forever;
 *           anything past the end clamps to it, so a renderer can just keep counting.
 *   scale:  int ≥ 1
 *   facing: 1 (default, hero faces right, the way he marches) | -1 mirrors
 *   gear:   the same [6 ints] you pass drawWarrior. The head keeps its helm, the fist keeps its sword, the
 *           ash keeps the cuirass — the build is visible right through the death.
 * }
 * Deterministic: every scatter here comes from hash32(seed), never a clock.
 * Returns { w, h } in device pixels.
 */
export function drawFatality(ctx, x, y, opts = {}) {
  DETAIL = opts.detail === 2 ? 2 : 1;
  const which = ((opts.which | 0) % FATALITIES.length + FATALITIES.length) % FATALITIES.length;
  const n = FATALITIES[which].frames;
  const f = Math.max(0, Math.min(n - 1, opts.frame | 0));
  const scale = Math.max(1, opts.scale | 0 || 1);
  const facing = opts.facing === -1 ? -1 : 1;
  const gear = opts.gear || EMPTY_GEAR;
  ctx.imageSmoothingEnabled = false;
  const gp = pen(ctx, x, y, scale, facing, false, null, FAT_W, FAT_H); // the gore/props pen: full frame
  // contact shadow first, on the ground, never rotated with the body
  for (let i = 0; i < 15; i++) if ((i & 1) === 0) gp.raw(MON_CX - 7 + i, MON_GROUND_Y, 1, 1, "#1a1420");
  FAT_FN[which](ctx, x, y, scale, facing, gear, f, gp);
  return { w: MON_W_N * scale, h: MON_H_N * scale };
}

/** Every frame of one fatality, laid out in a strip — for tuning the timing and for the visual test. */
export function drawFatalitySheet(ctx, x, y, opts = {}) {
  const which = ((opts.which | 0) % FATALITIES.length + FATALITIES.length) % FATALITIES.length;
  const n = FATALITIES[which].frames;
  const scale = Math.max(1, opts.scale | 0 || 1);
  for (let f = 0; f < n; f++) drawFatality(ctx, x + f * MON_W_N * scale, y, { ...opts, which, frame: f, scale });
  return { w: n * MON_W_N * scale, h: MON_H_N * scale, cells: n };
}
