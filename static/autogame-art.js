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

export const FRAME_W = 32;
export const FRAME_H = 32; // square ON PURPOSE: the death pose is the standing pose rotated 90°, which is
                           // only an exact integer-rect remap (no resampling, no gaps) when W === H.

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
// One shared skeleton in frame-local pixels. Every layer positions off these + the pose, so a helm never
// drifts off the head when a pose is retuned. Rows: 0-4 headroom (plumes/halo), 5-11 head, 12-20 torso,
// 21-29 legs, 30 ground.
const CX = 15;        // torso centre column
const HEAD_TOP = 5;
const TORSO_Y = 12, TORSO_W = 7, TORSO_H = 9;
const SHO_Y = 13;     // shoulder row (arms pivot here)
const HIP_Y = 21;
const KNEE_Y = 25;
const FOOT_Y = 29;    // last row of the body
const GROUND_Y = 30;  // contact shadow / grit

// Poses are hand-authored, not interpolated: at 24 px tall a computed in-between reads as a mistake, and
// hand-picked contact/pass frames are what make the walk legible at 1x.
//   bob   = torso+head sink (feet stay planted, so the whole body bobs against the ground)
//   lean  = torso x shift, sells the lunge
//   footF/footB, kneeF/kneeB = x offsets from the hip for front/back leg
//   hw/hs = absolute weapon-hand / shield-hand positions
//   dir   = weapon direction, restricted to the 8 compass steps so a stepped line stays crisp
const POSES = {
  walk: [
    { bob: 0, lean: 0, kneeF:  2, footF:  4, kneeB: -1, footB: -4, hw: [20, 15], hs: [13, 16], dir: [1, -1] }, // contact
    { bob: 1, lean: 0, kneeF:  1, footF:  1, kneeB:  0, footB: -1, hw: [19, 16], hs: [13, 17], dir: [1, -1] }, // pass
    { bob: 0, lean: 0, kneeF: -1, footF: -4, kneeB:  2, footB:  4, hw: [19, 15], hs: [14, 16], dir: [1, -1] }, // contact (mirrored legs)
    { bob: 1, lean: 0, kneeF:  0, footF: -1, kneeB:  1, footB:  1, hw: [20, 16], hs: [13, 17], dir: [1, -1] }, // pass
  ],
  attack: [
    { bob: 0, lean: -1, kneeF:  1, footF:  2, kneeB: -1, footB: -3, hw: [15, 12], hs: [12, 16], dir: [-1, -1] }, // wind-up, blade back
    { bob: 1, lean:  2, kneeF:  3, footF:  5, kneeB: -2, footB: -4, hw: [18, 17], hs: [14, 18], dir: [ 1,  0] }, // strike, lunge
    { bob: 0, lean:  1, kneeF:  2, footF:  3, kneeB: -1, footB: -3, hw: [19, 18], hs: [13, 17], dir: [ 1,  1] }, // follow-through, low
  ],
  // Drawn rotated 90° (see pen), so `dir:[1,-1]` lands on screen as down-forward: a dropped blade stuck in
  // the dirt. Limbs are splayed rather than mid-stride.
  dead: { bob: 0, lean: 0, kneeF: 3, footF: 5, kneeB: -3, footB: -5, hw: [20, 18], hs: [12, 18], dir: [1, -1] },
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
  const ROT_DY = 11; // after rotating, drop the lying body onto the ground line instead of mid-frame
                     // (warrior-only: nothing with a non-square frame may pass rot)
  const lx = bound ? bound.x0 : 0, ly = bound ? bound.y0 : 0;
  const hx = bound ? bound.x1 : fw, hy = bound ? bound.y1 : fh;
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
    /** the one primitive: an integer rect in frame-local, facing-right, standing coordinates */
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
      put(X, Y, W, H, col);
    },
    /** ground-anchored decals (contact shadow) must not tip over when the body does */
    raw(x, y, w, h, col) {
      let X = x | 0;
      if (flip) X = fw - X - (w | 0);
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

// shared attachment points, derived once per draw so a helm and a head can never disagree
function anchors(ps) {
  const torsoX = CX - 3 + (ps.lean >> 1), torsoY = TORSO_Y + ps.bob;
  return {
    torsoX, torsoY,
    headX: torsoX + 1, headY: HEAD_TOP + ps.bob,
    shoF: [torsoX + 5, SHO_Y + ps.bob], // front (weapon) shoulder
    shoB: [torsoX + 1, SHO_Y + ps.bob], // back (shield) shoulder
    hipF: torsoX + 4, hipB: torsoX + 2, hipY: HIP_Y + ps.bob,
  };
}

// ── affixes ──────────────────────────────────────────────────────────────────────────────
// One generic decorator applied by every layer to ITS OWN item box, so a blazing sword flames and a warding
// shield wards independently, and a full blazing set is unmistakable. `seed` de-phases the per-item
// animation (all six pieces flickering in lockstep looks like a bug, not an effect).
function affixAura(p, affix, box, frame, seed = 0) {
  const A = AFFIX_GLOW[affix | 0];
  if (!A || !p.fx) return;
  const f = frame & 3, { x, y, w, h } = box;
  switch (A.mode) {
    case "spark": { // keen — a glint hops corner to corner: reads as an edge you do not want to touch
      const pts = [[x + w - 1, y], [x, y + h - 1], [x + w - 1, y + h - 1], [x, y]];
      const [sx, sy] = pts[f];
      p.px(sx, sy - 1, 1, 3, A.glow);
      p.px(sx - 1, sy, 3, 1, A.glow);
      p.px(sx, sy, 1, 1, A.spark);
      break;
    }
    case "weight": { // heavy — the piece drags: a hard shadow under it and grit kicked off the ground
      p.dither(x, y + h, w, 2, A.glow, f & 1);
      p.px(x + (f & 1), GROUND_Y - 1, 1, 1, A.spark);
      p.px(x + w - 1 - (f & 1), GROUND_Y - 1, 1, 1, A.spark);
      break;
    }
    case "ward": { // warding — a dashed rune box standing off the item, rotating one pixel per frame
      const ox = x - 2, oy = y - 2, ow = w + 4, oh = h + 4;
      for (let i = 0; i < ow; i++) if (((i + f) & 1) === 0) { p.px(ox + i, oy, 1, 1, A.glow); p.px(ox + i, oy + oh - 1, 1, 1, A.glow); }
      for (let j = 0; j < oh; j++) if (((j + f) & 1) === 0) { p.px(ox, oy + j, 1, 1, A.glow); p.px(ox + ow - 1, oy + j, 1, 1, A.glow); }
      p.px(ox, oy, 1, 1, A.spark);
      p.px(ox + ow - 1, oy + oh - 1, 1, 1, A.spark);
      break;
    }
    case "streak": { // swift — speed lines trailing behind, lengths cycling so they read as motion at rest
      for (let i = 0; i < 3; i++) {
        const yy = y + 1 + i * Math.max(1, (h - 2) >> 1);
        p.px(x - 3 - ((f + i) & 3), yy, 2 + ((f + i) & 1), 1, i === 1 ? A.spark : A.glow);
      }
      break;
    }
    case "drip": { // vampiric — beads that fall out of the piece and reset: it is always bleeding something
      p.px(x + 1, y + h + ((f + seed) & 3), 1, 1, A.glow);
      p.px(x + w - 2, y + h + ((f + seed + 2) & 3), 1, 1, A.spark);
      break;
    }
    case "flame": { // blazing — tongues off the top edge, per-column heights from a fixed table
      for (let i = 0; i < w; i++) {
        const t = FLAME[(i + f * 3 + seed) % FLAME.length];
        if (!t) continue;
        p.px(x + i, y - t, 1, t, A.glow);
        p.px(x + i, y - t, 1, 1, A.spark);
      }
      break;
    }
    case "halo": { // hallowed — a short ring of light centred over the piece, plus a mote rising out of it.
      // Centred and capped at 6 px on purpose: six full-width bands (one per slot) turn into a cloud of
      // loose dashes floating beside the warrior instead of six haloes.
      const rw = Math.min(6, w + 2), rx = x + ((w - rw) >> 1);
      p.dither(rx, y - 3, rw, 2, A.glow, f & 1);
      p.px(rx + (rw >> 1), y - 4 - (f & 1), 1, 1, A.spark);
      break;
    }
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
  const len = 8 + tier;              // t0 barely past the belt, t7 sweeps the ankles
  const sway = SWAY[frame % SWAY.length];
  const top = a.shoF[1] - 1;
  for (let i = 0; i < len; i++) {
    const y = top + i;
    // Flare is spread over the WHOLE length, not ramped to its cap in the first few rows: a cloak that is
    // already at full width at the shoulder is a sail, and it swallows the body it is supposed to frame.
    // Only the bottom third swings, so the shoulders stay pinned to the walk.
    const flare = Math.round((i / Math.max(1, len - 1)) * (2 + (tier >> 1))) + (i > len - 4 ? sway : 0);
    const x0 = a.torsoX - 1 - flare;
    if (tier >= 5 && i >= len - 2 && ((x0 + i) & 1)) continue; // tattered hem on the high tiers
    p.px(x0, y, flare + 3, 1, i % 3 === 2 ? M.shade : M.base);
    p.px(x0, y, 1, 1, M.line);       // dark trailing edge keeps the silhouette off the background
    if (tier >= 2) p.px(x0 + 1, y, 1, 1, i % 2 ? M.shade : M.light); // fold
  }
  if (tier >= 3) { // mantle: the first thing that makes a cloak read as gear and not a towel
    p.px(a.torsoX - 2, top, 9, 2, M.base);
    p.px(a.torsoX - 2, top, 9, 1, M.light);
    p.px(a.torsoX - 2, top + 2, 9, 1, M.line);
  }
  if (tier >= 6) { // clasp
    p.px(a.torsoX + 5, top + 1, 2, 2, M.light);
    p.px(a.torsoX + 5, top + 2, 2, 1, M.line);
  }
  affixAura(p, affix, { x: a.torsoX - 8, y: top, w: 10, h: len }, frame, 5);
}

// one leg, drawn row by row: the x is lerped along hip→knee→foot so the limb bends without any curve math
function drawLeg(p, hipX, hipY, kneeDx, footDx, skin, boot, bootTop) {
  let fx = hipX;
  for (let y = hipY; y < FOOT_Y; y++) {
    const x = y <= KNEE_Y
      ? Math.round(hipX + kneeDx * (y - hipY) / Math.max(1, KNEE_Y - hipY))
      : Math.round(hipX + kneeDx + (footDx - kneeDx) * (y - KNEE_Y) / Math.max(1, FOOT_Y - 1 - KNEE_Y));
    const c = boot && y >= bootTop ? boot : skin;
    p.px(x, y, 2, 1, c.base);
    p.px(x, y, 1, 1, c.shade); // a single shaded column is enough to round a 2 px leg
    fx = x;
  }
  return fx;
}

function drawBoots(p, tier, mat, affix, frame, facing, ps) {
  const M = tier === null ? null : MATERIALS[mat];
  const a = anchors(ps);
  const bootTop = tier === null ? FOOT_Y : Math.max(HIP_Y + 1, FOOT_Y - (2 + tier)); // t0 ankle, t7 thigh
  // the far leg is drawn one ramp step darker — the cheapest way to keep two overlapping 2 px legs apart
  const far = M ? { base: M.shade, shade: M.line, light: M.base, line: M.line } : CLOTH;
  const foot = (fx, c, back) => {
    p.px(fx - 1, FOOT_Y, 4, 1, back ? c.shade : c.base);
    p.px(fx + 2, FOOT_Y, 1, 1, c.light);
    p.px(fx - 1, FOOT_Y, 1, 1, c.line);
    if (tier !== null && tier >= 6) p.px(fx + 3, FOOT_Y, 1, 1, c.light);     // sabaton toe
    if (tier !== null && tier >= 7) p.px(fx - 2, FOOT_Y - 1, 1, 1, c.light); // spur
  };
  const bx = drawLeg(p, a.hipB, a.hipY, ps.kneeB, ps.footB, CLOTH, M && far, bootTop);
  foot(bx, far, true);
  const fxp = drawLeg(p, a.hipF, a.hipY, ps.kneeF, ps.footF, SKIN, M, bootTop);
  foot(fxp, M || SKIN, false);
  if (M && tier >= 4) { // knee cop — the silhouette change that says "this is armour, not a shoe"
    p.px(a.hipF + ps.kneeF - 1, KNEE_Y - 1, 4, 2, M.base);
    p.px(a.hipF + ps.kneeF - 1, KNEE_Y - 1, 4, 1, M.light);
    p.px(a.hipF + ps.kneeF - 1, KNEE_Y + 1, 4, 1, M.line);
  }
  if (M) affixAura(p, affix, { x: a.hipB - 2, y: bootTop, w: 10, h: FOOT_Y - bootTop + 1 }, frame, 3);
}

function drawBody(p, tier, mat, affix, frame, facing, ps) {
  const M = tier === null ? CLOTH : MATERIALS[mat];
  const a = anchors(ps), x = a.torsoX, y = a.torsoY;
  // Drawn AFTER the legs on purpose: the fauld/skirt of a high-tier cuirass has to fall over the thighs.
  p.px(x, y, TORSO_W, TORSO_H, M.base);
  p.px(x, y, 1, TORSO_H, M.line);             // hard back edge: without it a same-material cloak and torso
  p.px(x + 1, y, 1, TORSO_H, M.shade);        // fuse into one unreadable blob
  p.px(x + TORSO_W - 1, y, 1, TORSO_H, M.light); // lit front edge
  p.px(x, y + TORSO_H - 1, TORSO_W, 1, M.line);
  p.px(x, y, TORSO_W, 1, M.line);
  if (tier === null) { // bare: an undershirt with an open collar, so the neck and chest still read as skin
    p.px(x + 2, y, 3, 2, SKIN.base);
    p.px(x + 3, y + 2, 1, 1, SKIN.shade);
    p.px(x + 1, y + 4, 5, 1, CLOTH.shade);
    return;
  }
  p.px(x + 2, y + 1, 3, 1, SKIN.base); // a sliver of neck under any breastplate keeps the figure human
  if (tier >= 1) { // belt
    p.px(x, y + 6, TORSO_W, 1, M.shade);
    p.px(x + 3, y + 6, 2, 1, M.light);
  }
  if (tier >= 2) p.px(x + 4, y + 2, 1, 4, M.light);  // chest ridge
  if (tier >= 3) { p.px(x + 1, y + 1, 5, 1, M.light); p.px(x + 1, y + 2, 5, 1, M.shade); } // gorget
  if (tier >= 4) { // fauld — the first big silhouette gain: the torso stops being a rectangle
    p.px(x, y + TORSO_H, TORSO_W, 2, M.base);
    p.px(x, y + TORSO_H + 1, TORSO_W, 1, M.shade);
    p.px(x + 3, y + TORSO_H, 1, 2, M.line);
  }
  if (tier >= 6) { p.px(x, y + TORSO_H + 2, TORSO_W - 1, 1, M.base); p.px(x, y + TORSO_H + 2, TORSO_W - 1, 1, M.shade); }
  if (tier >= 3) { // pauldrons, growing with tier — the width of the shoulders IS the tier read
    const pw = Math.min(5, 2 + ((tier - 2) >> 1));
    p.px(a.shoF[0] - pw + 2, a.shoF[1] - 2, pw, 3, M.base);
    p.px(a.shoF[0] - pw + 2, a.shoF[1] - 2, pw, 1, M.light);
    p.px(a.shoF[0] - pw + 2, a.shoF[1] + 1, pw, 1, M.line);
    if (tier >= 5) { // back pauldron too, and a spike off the front one
      p.px(a.shoB[0] - 1, a.shoB[1] - 2, pw - 1, 3, M.shade);
      p.px(a.shoF[0] + 1, a.shoF[1] - 3, 1, 2, M.light);
    }
    if (tier >= 7) { // winged pauldron + full trim: unmistakable, even as a 24 px silhouette
      p.px(a.shoF[0] + 1, a.shoF[1] - 4, 2, 1, M.light);
      p.px(a.shoF[0] + 2, a.shoF[1] - 5, 2, 1, M.base);
      p.px(a.shoB[0] - 2, a.shoB[1] - 4, 2, 1, M.light);
      p.px(x, y + 3, 1, 1, M.light);
      p.px(x + TORSO_W - 1, y + 3, 1, 1, M.light);
    }
  }
  affixAura(p, affix, { x, y, w: TORSO_W, h: TORSO_H }, frame, 1);
}

function drawHelm(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), x = a.headX, y = a.headY, W = 6, H = 7;
  p.px(x, y, W, H, SKIN.base);            // the head is always skin first; a helm is drawn ON it
  p.px(x, y, 1, H, SKIN.shade);
  p.px(x + W - 1, y + H - 1, 1, 1, SKIN.shade);
  if (tier === null) { // bare head: hair, ear, brow, eye, mouth — a face at 6x7 is 5 pixels of intent
    p.px(x, y, W, 2, HAIR.base);
    p.px(x, y, W - 1, 1, HAIR.shade);
    p.px(x, y + 2, 2, 2, HAIR.base);
    p.px(x + 4, y + 3, 1, 1, SKIN.line);  // eye
    p.px(x + 3, y + 2, 2, 1, HAIR.shade); // brow
    p.px(x + 2, y + 4, 1, 1, SKIN.shade); // ear
    p.px(x + 4, y + 5, 2, 1, SKIN.shade); // jaw/mouth
    affixAura(p, 0, { x, y, w: W, h: H }, frame, 2);
    return;
  }
  const M = MATERIALS[mat];
  p.px(x, y, W, 3, M.base);               // skull cap
  p.px(x, y, W, 1, M.light);
  p.px(x, y + 3, W, 1, M.line);           // brow rim
  p.px(x, y, 1, 3, M.shade);
  if (tier >= 1) p.px(x + 4, y + 3, 1, 2, M.base);                    // nasal bar
  if (tier >= 2) { // cheek plates close the face down to a slit — and the slit keeps ONE lit eye pixel, or
                   // the warrior stops looking alive
    p.px(x, y + 3, W, 3, M.base);
    p.px(x, y + 4, W, 1, M.line);
    p.px(x + 3, y + 4, 2, 1, "#ffcf6a");
    p.px(x, y + 3, 1, 3, M.shade);
    p.px(x + W - 1, y + 3, 1, 3, M.light);
  }
  if (tier >= 3) p.px(x + W, y + 3, 1, 1, M.light);                   // brow ridge pushes forward
  if (tier >= 4) { p.px(x + 1, y - 1, W - 2, 1, M.light); p.px(x + 2, y - 2, 2, 1, M.base); } // crest
  if (tier >= 5) { // horns, angled forward — the first read-at-a-glance tier tell on the head
    p.px(x + W - 1, y - 1, 1, 1, M.base);
    p.px(x + W, y - 2, 1, 2, M.light);
    p.px(x - 1, y - 1, 1, 1, M.shade);
  }
  if (tier >= 6) { // plume, swaying against the walk so the head never looks frozen
    const s = SWAY[frame % SWAY.length];
    const ph = tier >= 7 ? 5 : 3;
    for (let i = 0; i < ph; i++) p.px(x + 2 - ((i * s) >> 1), y - 2 - i, 2, 1, i & 1 ? M.shade : M.light);
    if (tier >= 7) { // back-swept plume tail + a crown of points: the tier-7 helm has a profile, not a cap
      for (let i = 0; i < 4; i++) p.px(x - 1 - i, y - 1 + i + s, 2, 1, i & 1 ? M.base : M.light);
      p.px(x, y - 1, 1, 1, M.light);
      p.px(x + W - 2, y - 1, 1, 1, M.light);
    }
  }
  affixAura(p, affix, { x, y, w: W, h: H }, frame, 2);
}

function drawShield(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), [hx, hy] = ps.hs;
  const M = tier === null ? null : MATERIALS[mat];
  // the far arm belongs to this layer: an empty shield slot still has to show a bare arm and fist
  const arm = M && tier >= 2 ? { base: M.shade, shade: M.line, light: M.base } : { base: SKIN.shade, shade: SKIN.line, light: SKIN.base };
  p.limb(a.shoB[0], a.shoB[1], hx, hy, 2, arm.base);
  p.px(hx, hy, 2, 2, arm.light);
  p.px(hx, hy + 1, 2, 1, arm.shade);
  if (!M) return;
  const w = 4 + ((tier * 5) >> 3);   // t0 buckler 4x5 … t7 tower 8x12
  const h = 5 + tier;
  const sx = hx - 1, sy = hy - ((h / 2) | 0);
  // outlined all round in `line`: a shield of the same material as the cuirass it hangs in front of has to
  // stay a separate object, and the outline is the only thing that does that at this size
  p.px(sx - 1, sy - 1, w + 2, h + 2, M.line);
  p.px(sx, sy, w, h, M.base);
  p.px(sx, sy, w, 1, M.light);
  p.px(sx, sy + h - 1, w, 1, M.line);
  p.px(sx, sy, 1, h, M.shade);
  p.px(sx + w - 1, sy, 1, h, M.light);
  p.px(sx + 1, sy + ((h / 2) | 0) - 1, 2, 2, M.light);  // boss
  if (tier >= 3) { p.px(sx, sy + ((h / 2) | 0), w, 1, M.shade); p.px(sx + ((w / 2) | 0), sy, 1, h, M.shade); } // bands
  if (tier >= 5) { // rivets
    p.px(sx + 1, sy + 1, 1, 1, M.light);
    p.px(sx + w - 2, sy + 1, 1, 1, M.light);
    p.px(sx + 1, sy + h - 2, 1, 1, M.light);
  }
  if (tier >= 6) { p.px(sx + 1, sy + h, w - 2, 1, M.base); p.px(sx + 2, sy + h + 1, w - 4, 1, M.shade); } // pointed foot
  if (tier >= 7) { p.px(sx + w, sy + ((h / 2) | 0) - 1, 2, 2, M.light); p.px(sx - 1, sy - 1, w + 2, 1, M.light); } // spike + trim
  affixAura(p, affix, { x: sx, y: sy, w, h }, frame, 4);
}

function drawWeapon(p, tier, mat, affix, frame, facing, ps) {
  const a = anchors(ps), [hx, hy] = ps.hw, [dx, dy] = ps.dir;
  const M = tier === null ? null : MATERIALS[mat];
  const arm = M && tier >= 4 ? { base: M.base, shade: M.shade, light: M.light } : { base: SKIN.base, shade: SKIN.shade, light: SKIN.light };
  p.limb(a.shoF[0], a.shoF[1], hx, hy, 2, arm.base);   // near arm, drawn last so it sits over the shield
  p.px(hx, hy, 2, 2, arm.light);
  p.px(hx, hy, 1, 2, arm.shade);
  if (!M) { p.px(hx, hy + 1, 2, 1, SKIN.line); return; } // bare fist: the unarmed pose is still a pose
  // t0 knife, t7 greatsword — LENGTH is the tier read. Clamped to the room actually left in the cell so the
  // TAPER lands on the last visible pixel: a blade chopped off flat by the frame edge reads as a bug, and
  // sprite cells sit shoulder to shoulder on a sheet, so growing the frame is not an option.
  const room = (at, d, edge) => (d > 0 ? (edge - 2 - at) / d : d < 0 ? (at - 1) / -d : 99);
  const fits = Math.floor(Math.min(room(hx, dx, FRAME_W), room(hy, dy, FRAME_H)));
  const len = Math.max(2, Math.min(4 + Math.round(tier * 1.4), fits));
  const th = tier >= 4 ? 2 : 1;                        // …thickness is not: past 2 px a diagonal blade
                                                       // stops being a blade and becomes a plank
  const guard = tier < 2 ? 0 : tier < 5 ? 1 : 2;       // likewise capped: a long crossguard on a diagonal
                                                       // blade reads as a second sword through the face
  p.px(hx - dx, hy - dy, 2, 2, M.shade);               // grip
  p.px(hx - dx * 2, hy - dy * 2, 2, 2, M.light);       // pommel
  // crossguard: perpendicular to the blade, so it stays a cross at every one of the 8 directions
  for (let i = -guard; i <= guard; i++) p.px(hx + dy * i, hy - dx * i, 1, 1, i === 0 ? M.light : M.base);
  let tipX = hx, tipY = hy;
  for (let i = 1; i <= len; i++) {
    const bx = hx + dx * i, by = hy + dy * i;
    if (bx < 0 || by < 0 || bx >= FRAME_W || by >= FRAME_H) break; // never let a long blade leave its cell
    const w = i > len - 2 ? 1 : tier >= 6 && i <= 3 ? th + 1 : th; // heavy at the ricasso, taper to a point
    p.px(bx, by, w, w, M.base);
    p.px(bx, by, 1, 1, M.light);                                   // lit edge down the whole blade
    if (tier >= 5 && i > 2 && i < len - 1) p.px(bx + w - 1, by + w - 1, 1, 1, M.shade); // fuller/back edge
    tipX = bx; tipY = by;
  }
  const bx0 = Math.min(hx, tipX), by0 = Math.min(hy, tipY);
  affixAura(p, affix, { x: bx0, y: by0, w: Math.abs(tipX - hx) + 2, h: Math.abs(tipY - hy) + 2 }, frame, 0);
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
  const sw = dead ? 20 : 11;
  for (let i = 0; i < sw; i++) if ((i & 1) === 0) p.raw((dead ? 5 : CX - 5) + i, GROUND_Y, 1, 1, "#1a1420");

  paintWarrior(p, gear, ps, frame, facing);
  return { w: FRAME_W * scale, h: FRAME_H * scale };
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
    drawWarrior(ctx, x + i * FRAME_W * scale, y, { ...opts, ...c, scale }));
  return { w: cells.length * FRAME_W * scale, h: FRAME_H * scale, cells: cells.length };
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
export const MON_W = 48;
export const MON_H = 48;
export const MON_CX = 24;        // centre column
export const MON_FOOT_Y = 44;    // last row the feet occupy…
export const MON_GROUND_Y = 45;  // …and the row the contact shadow lies on
export const PROP_W = MON_W;     // props share the box: one footX/footY conversion for the whole world layer
export const PROP_H = MON_H;

// Frame convention — the renderer indexes these directly, so they are exported rather than commented.
export const MON_IDLE_FRAMES = 3;   // 0,1,2 = idle/menace cycle (loop with frame % MON_IDLE_FRAMES)
export const MON_ATTACK_FRAME = 3;  // 3     = attack (lunge + swing + maw open)
export const MON_DEATH_FRAME = 4;   // 4     = death (collapsed heap; also forced by opts.dead)
export const MON_FRAMES = 5;
export const FAMILY_NAMES = ["grunt", "brute", "cannon"];
export const MON_RANK_NAMES = ["normal", "elite", "boss"];
export const PROP_KINDS = ["hazard", "cache", "shrine", "forge", "relic", "fork"];

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
const GRUNT_D = [ // small and hunched: the head is nearly half of it, and the ears are half of the head
  { bw:  8, bh:  8, hw:  8, hh:  7, leg: 5, legW: 2, ear: 4 },
  { bw: 10, bh: 10, hw: 10, hh:  9, leg: 6, legW: 3, ear: 5 },
  { bw: 16, bh: 13, hw: 15, hh: 13, leg: 8, legW: 5, ear: 8 },
];
// Kept nearly square: a body wider than it is tall reads as a QUADRUPED the moment you hang four visible
// limbs off it. The "heavy" is carried by wide shoulders over narrow hips instead.
const BRUTE_D = [
  { bw: 13, bh: 15, hw:  9, hh: 6, leg:  7, legW: 5, arm: 3 },
  { bw: 16, bh: 18, hw: 10, hh: 7, leg:  8, legW: 6, arm: 4 },
  { bw: 23, bh: 21, hw: 13, hh: 9, leg: 10, legW: 8, arm: 5 },
];
const CANNON_D = [ // a bell of robe on two bone stilts, hood on top, light in front
  { bw: 6, bh: 14, hw:  7, hh:  7, leg: 7, legW: 1, hem: 12 },
  { bw: 7, bh: 17, hw:  9, hh:  8, leg: 8, legW: 2, hem: 16 },
  { bw: 9, bh: 20, hw: 12, hh: 10, leg: 9, legW: 2, hem: 23 },
];

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
  p.px(x, y, 1, 1, "#ffffff");
  p.px(x + w - 1, y + h - 1, 1, 1, line); // pupil corner: without it the eye is a lamp, not an eye
}

// ── family: grunt ────────────────────────────────────────────────────────────────────────
// Small, hunched, more head than body, oversized ears and a cleaver it can barely hold. Reads as "there
// will be twelve of these" — which is exactly what a `fam 0` pull is.
function drawGrunt(p, R, C, ps, level) {
  const D = GRUNT_D[R], gy = MON_FOOT_Y;
  const legTop = gy - D.leg + 1;
  const byTop = legTop - D.bh + ps.bob;                 // torso
  const cx = MON_CX + 1;                                // body sits a touch behind the head
  const hcx = cx - 2 + ps.lean;                         // head juts forward over its toes
  const hy = byTop - D.hh + 1 + ps.bob;                 // …and sits ON TOP: this is a biped, not a beast
  const hx = hcx - (D.hw >> 1);

  legPair(p, cx - (D.bw >> 1) + 1, cx + (D.bw >> 1) - 1 - D.legW, legTop, D.legW, C.hide, 1 + R);
  // back arm, behind the torso: a scrap of silhouette on the far side so the body is not a flat card
  p.limb(cx + 2, byTop + 2, cx + (D.bw >> 1) + 1, byTop + D.bh - 1, 2, darker(C.hide).base);
  torso(p, cx, byTop, D.bh, D.bw, D.bw - 2, D.bw - 1, C.hide, -1); // hunched: shoulders over the toes
  p.px(cx - (D.bw >> 1), byTop + D.bh - 3, D.bw, 2, C.trim.base);  // rag belt
  p.px(cx - (D.bw >> 1), byTop + D.bh - 2, D.bw, 1, C.trim.shade);
  p.px(cx - (D.bw >> 1) + 1, byTop + D.bh - 1, 2, 2, C.trim.base); // loincloth scrap
  // dorsal spines — the level tell. COUNT only, never length: the silhouette stays the family's.
  const spines = Math.min(3, ((level | 0) / 6) | 0);
  for (let i = 0; i < spines; i++) horn(p, cx + (D.bw >> 1) - 1, byTop + 2 + i * 3, 1, -1, 3, C.trim);

  // head: wide, low-browed, and wider than the shoulders — that top-heavy read is the family
  torso(p, hcx, hy, D.hh, D.hw - 2, D.hw, D.hw - 3, C.hide, -1);
  horn(p, hx, hy + 2, -1, -1, D.ear, C.hide);                      // ears flare sideways, not up: at 1x
  horn(p, hx + D.hw - 1, hy + 2, 1, -1, D.ear - 1, C.hide);        // they are the whole grunt read
  const ey = hy + 2 + (R > 1 ? 1 : 0);
  p.px(hx + 1, ey - 1, 4 + R, 1, C.hide.line);                     // heavy brow
  eye(p, hx + 2, ey, 1 + R, 1 + R, C.eye, C.hide.line);
  p.px(hx, ey + 2, 2, 2, C.hide.light);                            // snout
  const my = hy + D.hh - 3 + (R > 1 ? 1 : 0);                      // maw, opening with the pose
  p.px(hx + 1, my, D.hw - 4, 1 + ps.jaw, C.hide.line);
  for (let i = 0; i < 2 + R; i++) p.px(hx + 2 + i * 2, my, 1, 1, "#f2e6c8"); // teeth
  if (ps.jaw) p.px(hx + 2, my + ps.jaw, D.hw - 6, 1, "#f2e6c8");             // lower row when it gapes

  // front arm + crude chopper. A slab on a stick, never a sword: it must not read as loot.
  const shx = cx - (D.bw >> 1) + 1, shy = byTop + 2;
  const hnx = shx - 2 - ps.arm, hny = byTop + 5 + (ps.arm > 2 ? 1 : 0);
  limbOut(p, shx, shy, hnx, hny, 2, C.hide);
  p.px(hnx - 1, hny - 1, 4, 4, C.hide.line);
  p.px(hnx, hny, 2, 2, C.hide.light);                              // fist
  // The chopper is a SLAB, not a stepped diagonal: at this size a 45° blade is three loose pixels, and the
  // grunt's weapon has to be legible enough that a swing has a cause.
  const up = ps.arm <= 2;                                          // idle rests it up, the attack chops down
  const bl = 4 + R * 2, bt = 3 + R * 2;
  p.px(hnx - 2, hny, 2, 2, C.trim.shade);                          // haft
  const bxp = hnx - 2 - bl, byp = hny - (up ? bt - 1 : 0);
  for (let j = 0; j < bt; j++) {
    const w = bl - Math.max(0, (up ? bt - 1 - j : j) - 1);         // taper away from the cutting edge
    p.px(bxp - 1, byp + j, w + 2, 1, C.trim.line);
    p.px(bxp, byp + j, w, 1, C.trim.base);
    p.px(bxp, byp + j, 1, 1, C.trim.light);
  }

  if (R >= 1) { // elite: an iron cap and a shoulder scale — the crowd's sergeant
    p.px(hx, hy - 2, D.hw - 2, 3, C.trim.base);
    p.px(hx, hy - 2, D.hw - 2, 1, C.trim.light);
    p.px(hx, hy + 1, D.hw - 2, 1, C.trim.line);
    p.px(cx - (D.bw >> 1), byTop - 1, 5, 3, C.trim.base);
    p.px(cx - (D.bw >> 1), byTop - 1, 5, 1, C.trim.light);
  }
  if (R >= 2) { // boss: a crown of horns and a bone bib — the doubled footprint does the rest
    horn(p, hx + 1, hy - 2, -1, -1, 4, C.trim);
    horn(p, hcx, hy - 3, 0, -1, 5, C.trim);
    horn(p, hx + D.hw - 2, hy - 2, 1, -1, 4, C.trim);
    p.px(cx - (D.bw >> 1) + 1, byTop + 1, D.bw - 3, 3, C.trim.base);
    p.px(cx - (D.bw >> 1) + 1, byTop + 1, D.bw - 3, 1, C.trim.light);
    p.px(cx - (D.bw >> 1) + 2, byTop + 4, D.bw - 5, 1, C.trim.shade);
  }
}

// ── family: brute ────────────────────────────────────────────────────────────────────────
// A wall. Twice as wide as it is interesting, head sunk between the shoulders, one arm dragging on the floor
// and a club the size of the grunt. Slow: the idle bob is the only thing that moves.
function drawBrute(p, R, C, ps, level) {
  const D = BRUTE_D[R], gy = MON_FOOT_Y;
  const legTop = gy - D.leg + 1;
  const byTop = legTop - D.bh + ps.bob;
  const cx = MON_CX, bx = cx - (D.bw >> 1);
  const hipW = D.bw - 6 - R * 2;                             // hips much narrower than the shoulders
  const atk = ps.arm > 2;

  legPair(p, cx - (hipW >> 1), cx + (hipW >> 1) - D.legW, legTop, D.legW, C.hide, 2 + R);

  // back arm, drawn BEFORE the body so the shoulder swallows its root; the club hangs off the hand
  const bsx = cx + (D.bw >> 1) - 3, bsy = byTop + 3;
  const bhx = atk ? cx - (D.bw >> 1) + 2 : cx + (D.bw >> 1) + 2;
  const bhy = atk ? byTop + 9 : byTop + 6;
  const dark = darker(C.hide);
  limbOut(p, bsx, bsy, bhx, bhy, D.arm, dark);
  p.px(bhx - 1, bhy - 1, D.arm + 2, D.arm + 2, dark.line);
  p.px(bhx, bhy, D.arm, D.arm, dark.base);
  // A maul: a shaft and a HEAD. A tapered chain of squares running out of the hand at 45° reads as a golf
  // club on its way out of the frame; a short shaft plus one heavy block reads as a weapon. Idle holds it
  // upright, the attack brings it down the front.
  const clen = (atk ? 5 : 4) + R * 2, hw2 = 4 + R;
  const cdx = atk ? -1 : 0, cdy = atk ? 1 : -1;               // straight up at rest, 45° forward on the swing
  for (let i = 1; i <= clen; i++) {
    const kx = bhx + cdx * i, ky = bhy + cdy * i;
    p.px(kx - 1, ky - 1, 4, 3, C.trim.line);
    p.px(kx, ky, 2, 2, C.trim.base);
    p.px(kx, ky, 1, 2, C.trim.light);
  }
  const mx = bhx + cdx * clen - ((hw2 - 2) >> 1), my2 = bhy + cdy * clen - (atk ? 0 : hw2 - 2);
  p.px(mx - 1, my2 - 1, hw2 + 2, hw2 + 2, C.trim.line);
  p.px(mx, my2, hw2, hw2, C.trim.base);
  p.px(mx, my2, 1, hw2, C.trim.light);
  p.px(mx, my2, hw2, 1, C.trim.light);
  for (let i = 1; i < hw2; i += 2) { p.px(mx - 1, my2 + i, 1, 1, C.trim.light); p.px(mx + hw2, my2 + i, 1, 1, C.trim.light); } // nails

  // the wedge: shoulders → gut → narrow hips. A brute is a triangle; a rectangle is a crate.
  torso(p, cx, byTop, D.bh, D.bw, D.bw - 3, hipW, C.hide, ps.lean);
  p.px(cx - (D.bw >> 1) + 4, byTop + D.bh - 7, D.bw - 11, 4, C.hide.light); // gut, catching the light
  p.px(cx - (hipW >> 1) - 1, byTop + D.bh - 2, hipW + 2, 2, C.trim.shade);  // belt
  p.px(cx - 1, byTop + D.bh - 2, 3, 2, C.trim.light);                       // buckle
  // scars — the level tell, short dark ticks across the chest
  const scars = Math.min(3, ((level | 0) / 6) | 0);
  for (let i = 0; i < scars; i++) p.px(bx + 4 + i * 4, byTop + 3 + i, 1, 4, C.hide.line);

  // head: sunk between the shoulders and shoved FORWARD, so it breaks the shoulder line on the front side
  // only — that overhang is what says "no neck" instead of "small head on a box".
  const hcx = cx - 2 + ps.lean, hy = byTop - D.hh + 1;
  const hx = hcx - (D.hw >> 1);
  // shoulder lumps on BOTH corners of the wedge: they are what the arms hang off, and they are the reason
  // the top of the body reads as shoulders rather than as the top of a crate
  for (const sxx of [cx - (D.bw >> 1) - 1, cx + (D.bw >> 1) - 3]) {
    p.px(sxx - 1, byTop, 6, 6, C.hide.line);
    p.px(sxx, byTop + 1, 4, 4, C.hide.base);
    p.px(sxx, byTop + 1, 4, 1, C.hide.light);
  }
  torso(p, hcx, hy, D.hh, D.hw - 2, D.hw, D.hw - 1, C.hide, -1);
  p.px(hx, hy + D.hh, D.hw, 1, C.hide.line);                  // neck shadow: without it the head is just
  p.px(hx + 1, hy, D.hw - 2, 1, C.hide.light);                // more shoulder. Skull lit on top for the same reason.
  p.px(hx, hy + 2, D.hw, 1, C.hide.line);                     // brow ridge over both eyes
  eye(p, hx + 1, hy + 3, 1 + (R > 1 ? 1 : 0), 1, C.eye, C.hide.line);
  eye(p, hx + 4 + R, hy + 3, 1 + (R > 1 ? 1 : 0), 1, C.eye, C.hide.line);
  // The jaw JUTS: a slab pushed out past the brow with the tusks coming up out of it. A brute whose mouth
  // is one dark line under two eyes reads as a helmet with a visor, not as a face.
  const my = hy + D.hh - 2;
  p.px(hx - 2, my - 1, D.hw - 1, 4 + ps.jaw, C.hide.line);
  p.px(hx - 1, my, D.hw - 3, 2 + ps.jaw, C.hide.base);
  p.px(hx - 1, my, D.hw - 3, 1, C.hide.shade);
  horn(p, hx, my - 1, 0, -1, 3 + R, C.trim);                  // tusks, pointing UP out of the lower jaw
  horn(p, hx + D.hw - 5, my - 1, 0, -1, 3 + R, C.trim);

  // front arm: OUTSIDE the silhouette on the front edge, hanging past the knee in idle — a brute's arms are
  // half the reason it is frightening and they were invisible while they ran down the inside of the body
  const fsx = cx - (D.bw >> 1) - 1, fsy = byTop + 2;
  const elx = fsx - 2, ely = byTop + ((D.bh * 2) / 3) | 0;    // an ELBOW: a straight column of arm beside a
  const fhx = cx - (D.bw >> 1) - 3 - ps.arm;                  // straight column of leg reads as four legs,
  const fhy = atk ? byTop + 1 : legTop - 1;                   // which is how this thing first came out
  limbOut(p, fsx, fsy, elx, ely, D.arm, C.hide);
  limbOut(p, elx, ely, fhx, fhy, D.arm - 1, C.hide);
  p.px(fhx - 1, fhy - 1, D.arm + 3, D.arm + 3, C.hide.line);  // fist, stopping clear of the ground
  p.px(fhx, fhy, D.arm + 1, D.arm + 1, C.hide.base);
  p.px(fhx, fhy, 1, D.arm + 1, C.hide.light);

  if (R >= 1) { // elite: a riveted shoulder plate, the first thing you see over the hero's head
    p.px(cx + 1, byTop - 2, 9, 4, C.trim.base);
    p.px(cx + 1, byTop - 2, 9, 1, C.trim.light);
    p.px(cx + 1, byTop + 2, 9, 1, C.trim.line);
    p.px(cx + 3, byTop - 1, 1, 1, C.trim.light);
    p.px(cx + 7, byTop - 1, 1, 1, C.trim.light);
  }
  if (R >= 2) { // boss: horns off the skull, a chest plate and a chain across the gut
    horn(p, hx, hy, -1, -1, 5, C.trim);
    horn(p, hx + D.hw - 1, hy, 1, -1, 5, C.trim);
    p.px(bx + 5, byTop + 2, D.bw - 11, 6, C.trim.base);
    p.px(bx + 5, byTop + 2, D.bw - 11, 1, C.trim.light);
    p.px(bx + 5, byTop + 8, D.bw - 11, 1, C.trim.line);
    for (let i = 0; i < D.bw - 12; i += 2) p.px(bx + 6 + i, byTop + 10 + (i & 2 ? 1 : 0), 1, 1, C.trim.light);
  }
}

// ── family: glass cannon ─────────────────────────────────────────────────────────────────
// Stilts, a robe and a light source. Nothing about it says "hit me and I survive" — which is the point: it
// pays the most renown and dies to one good swing.
function drawCannon(p, R, C, ps, level, frame) {
  const D = CANNON_D[R], gy = MON_FOOT_Y;
  const legTop = gy - D.leg + 1;
  const byTop = legTop - D.bh + ps.bob;
  const cx = MON_CX;
  const sway = SWAY[frame % SWAY.length];
  const atk = ps.arm > 2;

  legPair(p, cx - 2, cx + 2 - D.legW, legTop, D.legW, C.trim, 1); // bone stilts, under the hem

  // staff, planted on the back side — vertical, so it reads against every horizon
  const stx = cx + (D.hem >> 1) - 1, sty = byTop - 5 - R * 2;
  p.px(stx, sty, 1, gy - sty, C.trim.line);
  p.px(stx, sty, 1, gy - sty - 1, C.trim.base);
  p.px(stx - 1, sty - 3, 3, 4, C.hide.line);
  p.px(stx - 1, sty - 2, 3, 2, C.glow);
  p.px(stx, sty - 4, 1, 1, C.glow);

  // The robe IS the body: one bell from the shoulders to a hem past the knees. Drawn as a single tapered
  // mass rather than a torso plus a skirt, because two shapes at this size read as a seam, not a robe.
  const robeH = legTop - byTop + 3;
  torso(p, cx - (sway >> 1), byTop, robeH, D.bw, D.bw + 2 + R, D.hem, C.hide, ps.lean);
  for (let i = 0; i < D.hem; i += 2)                                  // ragged hem
    p.px(cx - (D.hem >> 1) + i, byTop + robeH - 1, 1, 2, C.hide.line);
  p.px(cx - (D.bw >> 1) - 1, byTop + 4, D.bw + 2, 1, C.hide.shade);   // a fold across the chest
  // runes down the robe — the level tell, and the only pure light on the body
  const runes = Math.min(3, ((level | 0) / 5) | 0);
  for (let i = 0; i < runes; i++) p.px(cx - 1 + (i & 1), byTop + 6 + i * 4, 2, 1, C.glow);

  // hood: a mass with a black void where a face should be, and two coals in it
  const hcx = cx - 1 + ps.lean, hy = byTop - D.hh + 2;
  const hx = hcx - (D.hw >> 1);
  torso(p, hcx, hy, D.hh, D.hw - 3, D.hw, D.hw - 2, C.hide, -1);
  horn(p, hx, hy + 1, -1, -1, 3 + R, C.hide);                  // hood peaks: one forward…
  horn(p, hx + D.hw - 1, hy + 2, 1, -1, 4 + R * 2, C.hide);    // …one swept back, longer
  const vw = D.hw - 4, vh = D.hh - 4;
  p.px(hx + 1, hy + 2, vw, vh, "#0b0a12");                     // the void
  eye(p, hx + 2, hy + 3, 1 + (R > 1 ? 1 : 0), 1 + (R > 1 ? 1 : 0), C.eye, "#0b0a12");
  eye(p, hx + 4 + R, hy + 3, 1 + (R > 1 ? 1 : 0), 1 + (R > 1 ? 1 : 0), C.eye, "#0b0a12");
  if (ps.jaw) p.px(hx + 2, hy + 2 + vh, vw - 2, 1, C.glow);    // it lights up before it speaks

  // casting arm + orb(s), held out FORWARD and clear of the hood — a floating light where a weapon should
  // be is the family read at distance, and it is worthless if it overlaps the face.
  const orbN = R + 1, pulse = [0, 1, 0, 2][frame % 4];
  const ahx = cx - (D.bw >> 1) - 3 - ps.arm, ahy = byTop + 3;
  limbOut(p, cx - (D.bw >> 1), byTop + 3, ahx, ahy, 1, C.trim);
  p.px(ahx - 1, ahy - 1, 3, 3, C.hide.line);
  p.px(ahx, ahy, 2, 2, C.trim.light);                          // skeletal hand
  for (let k = 0; k < orbN; k++) {
    const ang = (frame + k * 2) % 4;                           // fixed 4-step orbit: no trig, no clock
    const ox = ahx - 4 - [0, 1, 2, 1][ang] - k;      // stacked upward rather than fanned forward, or the
    const oy = ahy - 3 + [-1, 0, 1, 0][ang] - k * 4; // boss's third orb flares off the front of the cell
    const rr = 2 + R + pulse;
    for (let d = 2; d < 4 + (frame & 1); d++) { // flare: four spokes. A dithered box around the orb reads as
      p.px(ox + (rr >> 1), oy - d, 1, 1, C.glow); // a UI panel behind the sprite; spokes read as light.
      p.px(ox + (rr >> 1), oy + rr - 1 + d, 1, 1, C.glow);
      p.px(ox - d, oy + (rr >> 1), 1, 1, C.glow);
      p.px(ox + rr - 1 + d, oy + (rr >> 1), 1, 1, C.glow);
    }
    p.px(ox - 1, oy - 1, rr + 2, rr + 2, "#0b0a12");
    p.px(ox, oy, rr, rr, C.glow);
    p.px(ox, oy, 1, 1, "#ffffff");
  }
  if (atk) { // the bolt: the orb has left the hand and is on its way to the hero
    for (let i = 0; i < 6; i++) p.px(ahx - 7 - i, ahy - 1 + (i >> 2), 2, 1, i & 1 ? C.glow : C.eye);
    ring(p, ahx - 12, ahy - 3, 6, 6, C.glow, 1);
  }
  if (R >= 1) { // elite: a thin crown of spines around the hood
    for (let i = 0; i < 3; i++) horn(p, hx + 2 + i * ((D.hw - 3) >> 1), hy - 1, 0, -1, 3, C.trim);
  }
  if (R >= 2) { // boss: three runes hanging in the air beside it — it is holding the road hostage
    for (let i = 0; i < 3; i++) {
      const rx = cx + (D.hem >> 1) + 3, ry = byTop - 2 + i * 7 + ((frame + i) & 1);
      p.px(rx, ry, 3, 1, C.glow);
      p.px(rx + 1, ry - 1, 1, 3, C.glow);
      ring(p, rx - 1, ry - 2, 5, 5, C.glow, i & 1);
    }
  }
}

// ── death ────────────────────────────────────────────────────────────────────────────────
// A monster corpse is authored, not the standing pose knocked over: the point of frame 4 is that the road
// behind you is LITTERED, so it has to read as a heap in one glance. Sized by rank like everything else.
const CORPSE_D = [ // [family][rank] = [body w, body h]; the head is laid end-to-end with it
  [[11, 5], [14, 6], [19, 9]],
  [[17, 7], [20, 8], [24, 11]],
  [[13, 5], [16, 6], [21, 9]],
];
function drawCorpse(p, fam, R, C, level, frame) {
  const [w, h] = CORPSE_D[fam][R];
  const hw = Math.max(5, (w >> 2) + 3);                          // the head, and it needs to be BIG enough
  const left = MON_CX - ((hw + w) >> 1);                         // head + body laid end to end, centred
  const x = left + hw, y = MON_FOOT_Y - h + 1;                   // x = where the body starts
  // the ribcage/back of the body, tapering away from the shoulders
  torso(p, x + (w >> 1), y, h, w - 2, w, w - 4, C.hide, 0);
  p.dither(x + 1, y, w - 2, 2, C.hide.shade, 1);                 // the top of the heap, going cold
  // splayed limbs: one thrown forward, one folded back — the asymmetry is the only thing stopping a corpse
  // from reading as a rock
  limbOut(p, x + 2, y + 1, left - 1, MON_FOOT_Y, 2, darker(C.hide));
  p.px(left - 3, MON_FOOT_Y - 1, 3, 2, C.hide.shade);            // the hand it died reaching with
  limbOut(p, x + w - 4, y + 2, x + w + 2, MON_FOOT_Y - 4, 2, darker(C.hide));
  p.px(x + w + 1, MON_FOOT_Y - 6, 2, 3, C.hide.shade);
  // head, off the body, tipped over, eye out. It is drawn CLEAR of the mass with its own outline: a head
  // touching the body at this size is just more body.
  const hy = MON_FOOT_Y - hw + 1;
  torso(p, left + (hw >> 1), hy, hw, hw - 2, hw, hw - 3, C.hide, 0);
  p.px(left + (hw >> 1) - 2, hy + 2, 2, 1, C.hide.line);         // ✕ where the eye was
  p.px(left + (hw >> 1) - 1, hy + 1, 1, 3, C.hide.line);
  p.px(left + 1, hy + hw - 2, hw - 3, 1, "#f2e6c8");             // teeth, lolling open
  if (fam === 0) horn(p, left, hy + 1, -1, -1, 4, C.hide);                  // grunt keeps its ears
  if (fam === 1) { horn(p, left, hy, -1, -1, 5, C.trim); horn(p, left + hw - 1, hy, 1, -1, 4, C.trim); }
  if (fam === 2) { // the cannon's staff, fallen across it, still lit — the loot is still on the road
    for (let i = 0; i < 12; i++) p.px(x - 1 + i, MON_FOOT_Y - 5 + (i >> 2), 1, 1, C.trim.base);
    p.px(x - 3, MON_FOOT_Y - 5, 2, 2, C.glow);
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
  const sw = dead ? 22 + R * 6 : [13, 17, 27][R] + (fam === 1 ? 6 : 0);
  for (let i = 0; i < sw; i++) if ((i & 1) === 0) p.raw(MON_CX - (sw >> 1) + i, MON_GROUND_Y, 1, 1, "#1a1420");

  if (dead) drawCorpse(p, fam, R, C, level, opts.frame | 0);
  else {
    const ps = MON_POSES[Math.min(frame, MON_POSES.length - 1)];
    if (fam === 0) drawGrunt(p, R, C, ps, level);
    else if (fam === 1) drawBrute(p, R, C, ps, level);
    else drawCannon(p, R, C, ps, level, frame);
  }
  return { w: MON_W * scale, h: MON_H * scale };
}

/** The whole monster strip in one call — 3 idle, attack, death — for a bestiary widget or an offscreen bake. */
export function drawMonsterSheet(ctx, x, y, opts = {}) {
  const scale = Math.max(1, opts.scale | 0 || 1);
  for (let f = 0; f < MON_FRAMES; f++) drawMonster(ctx, x + f * MON_W * scale, y, { ...opts, frame: f, scale });
  return { w: MON_FRAMES * MON_W * scale, h: MON_H * scale, cells: MON_FRAMES };
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

function propHazard(p, f) { // a spiked, burning pit — the tile that chips you if you do not dodge
  const gy = MON_FOOT_Y;
  p.px(MON_CX - 9, gy, 18, 1, "#20161a");                       // scorched ground
  p.dither(MON_CX - 11, gy - 1, 22, 2, "#3a2418", f & 1);
  for (let i = 0; i < 4; i++) {                                  // spikes, alternating heights
    const sx = MON_CX - 8 + i * 5, sh = 5 + (i & 1) * 3;
    horn(p, sx, gy - 1, 0, -1, sh, IRON);
  }
  for (let i = 0; i < 18; i++) {                                 // flame tongues off the coal bed
    const t = FLAME[(i + f * 3) % FLAME.length] + 2;
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, t, FIRE.shade);
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, (t >> 1) + 1, FIRE.base);
    p.px(MON_CX - 9 + i, gy - 1 - t, 1, 1, FIRE.light);
  }
  p.px(MON_CX - 8, gy - 1, 16, 1, FIRE.shade);                   // embers under it all
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
  p.px(x + ((w >> 1) - 1), y + 2, 3, 4, GOLD.base);               // lock plate, front and centre
  p.px(x + ((w >> 1) - 1), y + 2, 3, 1, GOLD.light);
  p.px(x + (w >> 1), y + 3, 1, 2, GOLD.line);                     // keyhole
  p.dither(x + 1, y - 1 - lift, w - 2, 1 + lift, GOLD.light, f & 1); // the glow escaping the seam
  p.px(x - 1, y - 4 - lift, w + 2, 4, WOOD.line);                 // the lid, tipped back off the seam
  p.px(x, y - 3 - lift, w, 3, WOOD.base);
  p.px(x, y - 3 - lift, w, 1, WOOD.light);
  p.px(x + 2, y - 3 - lift, 2, 3, IRON.base);
  p.px(x + w - 4, y - 3 - lift, 2, 3, IRON.base);
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
  step(14, gy - 15, 5, STONE);          // bowl
  p.px(MON_CX - 6, gy - 14, 12, 3, WATER.base);
  p.dither(MON_CX - 6, gy - 14, 12, 2, WATER.light, f & 1);       // surface, catching the sky
  for (const sx of [MON_CX - 7, MON_CX + 5]) {                    // water running over the lip
    p.px(sx, gy - 12, 2, 3 + ((f + 1) % 3), WATER.base);
    p.px(sx, gy - 12, 1, 2, WATER.light);
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
  p.px(MON_CX - 5, gy - 1, 10, 1, WOOD.line);
  p.px(MON_CX - 8, gy - 12, 15, 3, IRON.base);                    // anvil face + horn
  p.px(MON_CX - 8, gy - 12, 15, 1, IRON.light);
  p.px(MON_CX - 10, gy - 11, 2, 1, IRON.base);
  p.px(MON_CX - 3, gy - 9, 5, 3, IRON.shade);                     // waist
  p.px(MON_CX - 6, gy - 6, 11, 2, IRON.base);                     // base
  p.px(MON_CX - 6, gy - 6, 11, 1, IRON.light);
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
  p.px(MON_CX - 1, cy + 1, 2, 1, "#ffffff");                        // core
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
  p.px(px0 - 1, gy - 1, 4, 1, WOOD.line);
  const board = (by, dir, C) => {                                   // an arrow board: rect + a pointed end
    const w = 10, bx = dir < 0 ? px0 - w - 1 : px0 + 2;
    p.px(bx - 1, by - 1, w + 2, 6, WOOD.line);
    p.px(bx, by, w, 4, C.base);
    p.px(bx, by, w, 1, C.light);
    const tip = dir < 0 ? bx - 1 : bx + w;
    p.px(tip, by + 1, 1, 2, C.base);
    p.px(tip + (dir < 0 ? -1 : 1), by + 2, 1, 1, C.base);
    for (let i = 2; i < w - 1; i += 3) p.px(bx + i, by + 2, 2, 1, C.line); // "writing"
  };
  board(gy - 19, -1, WOOD);
  board(gy - 12, 1, { base: "#a05a2a", shade: WOOD.shade, light: "#d08a4a", line: WOOD.line });
  p.px(px0 - 1, gy - 21, 4, 1, WOOD.shade);                          // cap
  if (f & 1) p.px(px0 + 3, gy - 22, 1, 1, GOLD.light);               // a glint off the nail: it is not dead
}

/**
 * Draw one prop with its TOP-LEFT CORNER at (x, y) — same convention and the same PROP_W × PROP_H
 * (= MON_W × MON_H) box as drawMonster, so the world renderer converts ground coordinates once and uses it
 * for every tile.
 * opts = { kind: "hazard"|"cache"|"shrine"|"forge"|"relic"|"fork" (or its index in PROP_KINDS),
 *          frame: int — flame flicker / lid breath / gem pulse, cycle length 3 (frame % 3 is enough),
 *          scale: int ≥ 1, facing: 1|-1 (only the fork really cares) }
 * Deterministic: nothing here reads a clock.
 */
export function drawProp(ctx, x, y, opts = {}) {
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
    default: return { w: PROP_W * scale, h: PROP_H * scale }; // unknown kind draws NOTHING rather than a
                                                             // wrong thing — the caller keeps its fallback
  }
  return { w: PROP_W * scale, h: PROP_H * scale };
}

// ══ BLOOD ════════════════════════════════════════════════════════════════════════════════
// Every fight leaves a mark. This is a separate layer rather than something baked into the monster art
// because the renderer needs to put blood on BOTH sides of a swing, keep a pool under a corpse for the rest
// of the chapter, and lay dried splatter on road the player has already walked.
//
// Determinism is not optional here: the whole game replays from two block hashes, so a splatter has to be a
// pure function of (seed, kind, frame, amount). `seed` is the caller's — a step index, a run id, anything —
// and is run through an integer hash so consecutive seeds do not produce near-identical sprays.
export const BLOOD_W = MON_W;
export const BLOOD_H = MON_H;
export const BLOOD_KINDS = ["hit", "spurt", "pool", "splatter"];
// frames per kind; a caller that runs past the end just gets the last frame (spray gone, pool full grown)
export const BLOOD_FRAMES = { hit: 5, spurt: 7, pool: 6, splatter: 1 };

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
  drawBloodInto(p, kind, opts);
  return { w: BLOOD_W * scale, h: BLOOD_H * scale };
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
export const FAT_W = MON_W;
export const FAT_H = MON_H;
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
  const p = pen(ctx, x + ox * scale, y + oy * scale, scale, facing, !!rot, recolor || null,
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
  return { w: FAT_W * scale, h: FAT_H * scale };
}

/** Every frame of one fatality, laid out in a strip — for tuning the timing and for the visual test. */
export function drawFatalitySheet(ctx, x, y, opts = {}) {
  const which = ((opts.which | 0) % FATALITIES.length + FATALITIES.length) % FATALITIES.length;
  const n = FATALITIES[which].frames;
  const scale = Math.max(1, opts.scale | 0 || 1);
  for (let f = 0; f < n; f++) drawFatality(ctx, x + f * FAT_W * scale, y, { ...opts, which, frame: f, scale });
  return { w: n * FAT_W * scale, h: FAT_H * scale, cells: n };
}
