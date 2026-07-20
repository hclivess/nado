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
function pen(ctx, ox, oy, scale, facing, rot, recolor) {
  const s = Math.max(1, scale | 0);
  const flip = facing < 0;
  const ROT_DY = 11; // after rotating, drop the lying body onto the ground line instead of mid-frame
  const put = (X, Y, W, H, col) => {
    if (X < 0) { W += X; X = 0; }
    if (Y < 0) { H += Y; Y = 0; }
    if (X + W > FRAME_W) W = FRAME_W - X;
    if (Y + H > FRAME_H) H = FRAME_H - Y;
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
      let X = x, Y = y, W = w, H = h;
      if (rot) { X = FRAME_H - y - h; Y = x + ROT_DY; W = h; H = w; } // 90° CW, exact because W === H
      if (flip) X = FRAME_W - X - W;
      put(X, Y, W, H, col);
    },
    /** ground-anchored decals (contact shadow) must not tip over when the body does */
    raw(x, y, w, h, col) {
      let X = x | 0;
      if (flip) X = FRAME_W - X - (w | 0);
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

  const it = gear.map(unpackItem);
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
  return { w: FRAME_W * scale, h: FRAME_H * scale };
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
