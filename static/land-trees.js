// land-trees.js — the forest's drawn models (imported by the mesher worker, static/land-mesher.js). Pure geometry: no
// three.js, no DOM.
//
// THE CELLS ARE THE TREE; THIS IS ITS PICTURE ("overall not impressive", operator 2026-11-06; fidelity bar: a custom-
// engine forest showcase). A tree's cells (land-world treeAt/treeCell) stay the data — what is gathered, what blocks a
// walker, what the server and the commitment see. While every one of a tree's cells is untouched the mesher draws THIS
// model in their place: a tapered trunk that forks into limbs and twigs, carrying alpha-cut leaf cards from a painted
// atlas (static/land.js paintLeaves), every vertex weighted for the wind. A tree someone has cut into is drawn as its
// cells again, so the picture never shows wood that is no longer there.
//
// GROWN, NOT HAND-PLACED (2026-11-08, #138): broadleaf, birch, conifer and bush grow from Solstice's species recipes —
// an oak, a silver birch, a fir, a bush — by its growth (static/land-species.js, MIT), fitted here to Land's cells,
// footprint and budget; only the palm, which Solstice has no recipe for, is still built by hand below.
//
// A model is a function of (kind, height, seed, lod) — the same tree on every screen. Local axes: x east, y north, z up,
// metres from the root at ground level. Every model stays inside its tree's cells' footprint (2 columns around the root,
// TREE_REACH above), so no tree is drawn over a neighbouring plot.
//
// Leaf atlas: 2 x 2 tiles, (t & 1, t >> 1) — 0 broadleaf cluster, 1 birch cluster, 2 needle spray (twig along v),
// 3 palm frond (rachis along v). Bark: tile 0 bark, 1 birch (static/land.js picks the texture).
import { growPlant, ADAPT, at } from "./land-species.js";
export const LEAF_TILE = { broadleaf: 0, birch: 1, conifer: 2, palm: 3, bush: 0 };
export const REACH = 2.45;                     // no vertex further than this from the trunk's axis (the cells reach 2.5)

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const dirAt = (az, el) => [Math.cos(az) * Math.cos(el), Math.sin(az) * Math.cos(el), Math.sin(el)];
// keep a point inside the footprint: pull it toward the axis when it strays past REACH
const clampR = (p) => { const r = Math.hypot(p[0], p[1]); return r <= REACH ? p : [p[0] * REACH / r, p[1] * REACH / r, p[2]]; };

function part() { return { pos: [], nor: [], uv: [], tile: [], col: [], wind: [], n: 0, idx: [] }; }

/** A tapered tube along `pts` ([[x,y,z], ...]) with radii `rad`; sway(i) is the wind weight of ring i. */
function tube(b, pts, rad, sides, sway, tile, tint) {
  const base = b.n;
  let len = 0;
  for (let i = 0; i < pts.length; i++) {
    if (i) len += Math.hypot(...sub(pts[i], pts[i - 1]));
    const d = norm(sub(pts[Math.min(i + 1, pts.length - 1)], pts[Math.max(i - 1, 0)]));
    let a = norm(cross(d, Math.abs(d[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), c = cross(d, a);
    for (let s = 0; s <= sides; s++) {
      const ang = (s / sides) * Math.PI * 2, ca = Math.cos(ang), sa = Math.sin(ang);
      const nrm = add(mul(a, ca), mul(c, sa));
      const p = add(pts[i], mul(nrm, rad[i]));
      b.pos.push(p[0], p[1], p[2]); b.nor.push(nrm[0], nrm[1], nrm[2]);
      b.uv.push((s / sides) * Math.max(1, Math.round(rad[i] * 8)) * 0.5, len / 1.6);   // bark at about its true scale
      b.tile.push(tile); b.col.push(tint[0], tint[1], tint[2]);
      b.wind.push(sway(i), 0, 0, 0);
      b.n++;
    }
  }
  for (let i = 0; i + 1 < pts.length; i++) for (let s = 0; s < sides; s++) {
    const r0 = base + i * (sides + 1) + s, r1 = r0 + sides + 1;
    b.idx.push(r0, r0 + 1, r1 + 1, r0, r1 + 1, r1);
  }
}

/** A leaf card: centre c, its in-plane axes ax (along u, half-width) and ay (along v, half-height). The normal leans
 *  toward `out` (away from the crown's centre), which lights a crown as a soft volume instead of flat cards. */
function card(b, c, ax, ay, tile, out, sway, tint) {
  const base = b.n, tu = (tile & 1) * 0.5, tv = (tile >> 1) * 0.5, e = 0.004;
  // ...and toward the sky: a crown's underside and a bush's flank are lit by the open sky above them, and normals that
  // followed the cards alone rendered every bush and shaded crown nearly black (the first model render)
  const fn = norm(cross(ax, ay)), o = norm(out), n = norm(add(add(mul(dot(fn, o) < 0 ? mul(fn, -1) : fn, 0.3), mul(o, 0.6)), [0, 0, 0.4]));
  for (const [s, t] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const p = clampR(add(c, add(mul(ax, s), mul(ay, t))));
    b.pos.push(p[0], p[1], p[2]); b.nor.push(n[0], n[1], n[2]);
    b.uv.push(tu + e + (s + 1) / 2 * (0.5 - 2 * e), tv + e + (t + 1) / 2 * (0.5 - 2 * e));
    b.tile.push(tile); b.col.push(tint[0], tint[1], tint[2]);
    b.wind.push(sway, 0, 0, 1);                                  // w = 1: a leaf (it flutters as well as sways)
    b.n++;
  }
  b.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
}
/** A card facing a random way, `size` metres across, its texture's up roughly up. */
function cluster(b, R, c, size, tile, centre, sway, tint) {
  const az = R() * Math.PI * 2, tilt = (R() - 0.5) * 1.4;
  const ax = mul([Math.cos(az), Math.sin(az), 0], size / 2);
  const ay = mul(norm([-Math.sin(az) * Math.sin(tilt), Math.cos(az) * Math.sin(tilt), Math.cos(tilt)]), size / 2);
  card(b, c, ax, ay, tile, sub(c, centre), sway, tint);
}
/** A curved limb from p0 heading d for `len` m, bending by `bend` per m (toward +z if positive), as points. */
function limb(p0, d, len, bend, segs) {
  const pts = [p0];
  let p = p0, dir = norm(d);
  for (let i = 1; i <= segs; i++) {
    dir = norm(add(dir, [0, 0, bend * len / segs]));
    p = clampR(add(p, mul(dir, len / segs)));
    pts.push(p);
  }
  return pts;
}
const tintOf = (R, base, spread) => { const j = 1 - spread / 2 + R() * spread; return [base[0] * j, base[1] * j, base[2] * j]; };

/** A tree GROWN from its species recipe (land-species.js — Solstice's growth, adapted to Land): its stems as tubes (the
 *  finest twigs carried by their leaves alone; far away the trunk and limbs only), its leaves as alpha cards along its
 *  outermost shoots — a needle spray along each conifer shoot — to the level of detail's budget. */
function grownModel(kind, H0, R, lod) {
  const bark = part(), leaves = part(), A = ADAPT[kind], far = lod >= 2, top = A.top(H0), brown = [1, 1, 1];
  const { stems, leafy, centre } = growPlant(kind, H0, R, lod);
  const barkTile = kind === "birch" ? 1 : 0;
  for (const s of stems) {
    // the finest stems are carried by their leaves alone (a twig thinner than a pencil is not seen as wood), and a
    // stem's sides follow its girth — a trunk is round, a branch three-sided
    if (s.depth > A.wood[far ? 1 : 0] || (s.depth === 2 && s.radii[0] < 0.012)) continue;
    const sides = s.depth === 0 ? (far ? 5 : 7) : s.depth === 1 && s.radii[0] >= 0.05 && !far ? 5 : 3;
    const last = s.pts.length - 1;
    // the wind: a trunk sways from its crown, a limb more toward its tip, a twig most
    tube(bark, s.pts.map(clampR), s.radii, sides, (i) => 0.02 * (s.pts[i][2] / top) ** 2 + 0.035 * s.depth * (i / last), barkTile, brown);
  }
  // the tree's leaf cards shared out over its outermost shoots by their length
  const total = leafy.reduce((n, i) => n + stems[i].len, 0) || 1, budget = A.cards[far ? 2 : 0], grow = far ? 1.35 : 1;
  const longest = Math.max(...leafy.map((i) => stems[i].len), 1e-6);
  for (const i of leafy) {
    const s = stems[i], count = Math.max(1, Math.round((budget * s.len) / total));
    for (let k = 0; k < count; k++) {
      // mostly toward the tip, where the newest growth is (tree.rs add_leaves)
      const t = A.sprays ? (k + 0.5) / count : 0.25 + 0.75 * Math.pow((k + R()) / count, 0.7), { p, d } = at(s, t);
      const size = (A.card[0] + R() * (A.card[1] - A.card[0])) * grow, sway = 0.1 + 0.08 * (p[2] / top) + 0.05 * R();
      const tint = tintOf(R, [1, 1, 1], kind === "conifer" ? 0.2 : 0.3);
      if (A.sprays) {                                     // needle sprays along the branch, end to end: the twig along v
        // a spray as wide as its branch is long allows: short branches near the top carry narrow sprays, so the crown
        // narrows to a point as a fir's does (fixed-width sprays padded the top out and blunted the cone)
        const wide = size * (0.3 + 0.7 * s.len / longest);
        const side = norm(cross(d, [0, 0, 1])), along = mul(d, (s.len / count) * 0.62), out = add(sub(p, centre), [0, 0, 0.2]);
        card(leaves, p, mul(side, wide), along, A.tile, out, sway, tint);
        if (!far) card(leaves, add(p, [0, 0, 0.04]), mul(norm(add(mul(side, 0.5), [0, 0, 0.85])), wide * 0.8), along, A.tile, out, sway, tint);
      } else {
        const hang = kind === "birch" ? [0, 0, -0.12 - R() * 0.2] : [0, 0, 0];   // a birch's leaves hang from its twigs
        cluster(leaves, R, add(p, add(hang, [(R() - 0.5) * 0.3, (R() - 0.5) * 0.3, (R() - 0.5) * 0.25])), size, A.tile, centre, sway, tint);
      }
    }
  }
  // a conifer's leader: the trunk's tip in needles, so no bare pole stands above the crown
  if (A.sprays) cluster(leaves, R, stems[0].pts[stems[0].pts.length - 1], 0.45, A.tile, add(stems[0].pts[stems[0].pts.length - 1], [0, 0, -1]), 0.1, [1, 1, 1]);
  return { bark, leaves };
}

/** { bark, leaves } for a tree: kind and height as land-world treeAt gives them, seed from its root, lod 0..2. */
export function treeModel(kind, height, seed, lod = 0) {
  const R = rng(seed), bark = part(), leaves = part();
  const far = lod >= 2, sides = far ? 4 : 7, keep = far ? 0.5 : 1, grow = far ? 1.35 : 1;   // far: half the cards, larger
  const takeCard = () => keep >= 1 || R() < keep;
  const brown = [1, 1, 1], H0 = height;
  if (ADAPT[kind]) return grownModel(kind, H0, R, lod);
  if (kind === "palm") {
    const top = H0 + 0.7, az0 = R() * Math.PI * 2, lean = 0.5 + R() * 0.5;
    const tr = [0, 0.2, 0.4, 0.6, 0.8, 1].map((f) => [Math.cos(az0) * lean * f * f, Math.sin(az0) * lean * f * f, -0.3 + f * (top + 0.3)]);
    tube(bark, tr, [0.26, 0.2, 0.18, 0.17, 0.16, 0.17], sides, (i) => 0.035 * (i / 5) ** 2, 0, [1.15, 1.05, 0.9]);
    const crown = tr[tr.length - 1], nf = far ? 7 : 10;
    for (let k = 0; k < nf; k++) {
      // a frond: a strip that rises out of the crown and arches down, the rachis along v, widest a third of the way
      const az = (k / nf) * Math.PI * 2 + R() * 0.3, ln = 2.2 + R() * 0.5, segs = far ? 3 : 6;
      const pts = [crown], dir0 = dirAt(az, 0.75 - R() * 0.2);
      let p = crown, d = dir0;
      for (let s = 1; s <= segs; s++) { d = norm(add(d, [0, 0, -0.32])); p = clampR(add(p, mul(d, ln / segs))); pts.push(p); }
      const side = norm(cross(dir0, [0, 0, 1])), tu = (3 & 1) * 0.5, tv = (3 >> 1) * 0.5, base = leaves.n;
      for (let s = 0; s <= segs; s++) {
        const f = s / segs, w = Math.sin(Math.min(1, f * 1.5 + 0.05) * Math.PI) * 0.55 + 0.05;
        const dn = norm(cross(side, sub(pts[Math.min(s + 1, segs)], pts[Math.max(s - 1, 0)])));
        const up = dn[2] < 0 ? mul(dn, -1) : dn;
        for (const sg of [-1, 1]) {
          const q = clampR(add(pts[s], add(mul(side, sg * w), [0, 0, -Math.abs(sg) * w * 0.25])));   // leaflets droop
          leaves.pos.push(q[0], q[1], q[2]); leaves.nor.push(up[0], up[1], up[2]);
          leaves.uv.push(tu + 0.004 + (sg + 1) / 2 * 0.492, tv + 0.004 + f * 0.492);
          leaves.tile.push(3); leaves.col.push(1, 1, 1); leaves.wind.push(0.06 + 0.22 * f, 0, 0, 1); leaves.n++;
        }
      }
      for (let s = 0; s < segs; s++) { const a = base + s * 2; leaves.idx.push(a, a + 1, a + 3, a, a + 3, a + 2); }
    }
  }
  return { bark, leaves };
}

/** A placed leaf cell: a small cluster of cards in one cell (centred on it, inside it), in leaf tile `tile`. */
const cellModels = new Map();
export function leafCellModel(tile) {
  if (cellModels.has(tile)) return cellModels.get(tile);
  const R = rng(1000 + tile), bark = part(), leaves = part();
  for (let k = 0; k < 6; k++) {
    const c = [(R() - 0.5) * 0.4, (R() - 0.5) * 0.4, (R() - 0.5) * 0.4];
    cluster(leaves, R, c, 0.75 + R() * 0.2, tile, [0, 0, -0.3], 0.08, tintOf(R, [1, 1, 1], 0.2));
  }
  const m = { bark, leaves };
  cellModels.set(tile, m);
  return m;
}

/** A fallen stick on the ground (land-world LITTER): a crooked length of branch with a fork, lying flat. */
/** A clump of flax (land-world B.flax): thin upright stems, 55-85 cm, each topped with a small sky-blue flower — it grows
 *  in stands on the meadows and is pulled up by hand for its fibre ("adding additional recipes and materials ... in a
 *  sensible, realistic yet engaging manner", operator 2026-11-07). Stems in the bark part, tinted green; flowers too. */
export function flaxModel(seed) {
  const R = rng(seed), bark = part(), leaves = part(), n = 6 + Math.floor(R() * 4);
  for (let k = 0; k < n; k++) {
    const a = R() * Math.PI * 2, r = 0.05 + R() * 0.13, h = 0.55 + R() * 0.3, lean = (R() - 0.5) * 0.12;
    const b0 = [Math.cos(a) * r, Math.sin(a) * r, 0], top = [b0[0] + Math.cos(a) * lean, b0[1] + Math.sin(a) * lean, h];
    const mid = [(b0[0] + top[0]) / 2, (b0[1] + top[1]) / 2, h * 0.5];
    // the tints LIFT the bark texture (a dark brown) to a fresh green stem and a sky-blue flower — at 1x they drew black
    tube(bark, [b0, mid, top], [0.009, 0.007, 0.005], 3, (i) => i * 0.35, 0, [1.3, 2.9, 1.1]);
    tube(bark, [add(top, [0, 0, -0.01]), add(top, [0, 0, 0.035])], [0.03, 0.016], 6, () => 0.7, 0, [1.7, 2.7, 6.2]);   // the flower
  }
  return { bark, leaves };
}
/** A wild flower (land-world FLOWERS): a few stems, 25-45 cm, each topped with its flower head — kind 0 a red poppy
 *  (a wide cup), 1 a blue cornflower, 2 a white daisy (a flat disc), 3 a yellow buttercup (a small cup). The tints LIFT
 *  the bark texture, as flax's do, so the colours read true. */
const FLOWER_TINT = [[6.2, 0.9, 0.7], [1.2, 1.7, 6.4], [5.8, 5.8, 5.5], [6.0, 4.9, 0.8]];
const EYE_TINT = [[0.6, 0.5, 0.5], [1.4, 1.6, 4.5], [6.0, 4.6, 0.7], [5.0, 3.6, 0.5]];
export function flowerModel(seed, kind) {
  const R = rng(seed), bark = part(), leaves = part(), n = 5 + Math.floor(R() * 4), tint = FLOWER_TINT[kind] || FLOWER_TINT[0];
  // petals radiate from the head: a poppy's five broad ones cupped up, a cornflower's ragged ring, a daisy's many thin
  // white rays laid flat round a yellow eye, a buttercup's five small cupped ones
  const petals = [5, 8, 12, 5][kind] ?? 5, len = [0.055, 0.04, 0.05, 0.03][kind] ?? 0.04, rad = [0.022, 0.01, 0.008, 0.014][kind] ?? 0.01;
  const lift = [0.03, 0.015, 0.004, 0.02][kind] ?? 0.01;
  for (let k = 0; k < n; k++) {
    const a = R() * Math.PI * 2, r = 0.04 + R() * 0.14, h = 0.3 + R() * 0.25, lean = (R() - 0.5) * 0.1;
    const b0 = [Math.cos(a) * r, Math.sin(a) * r, 0], top = [b0[0] + Math.cos(a) * lean, b0[1] + Math.sin(a) * lean, h];
    const mid = [(b0[0] + top[0]) / 2, (b0[1] + top[1]) / 2, h * 0.5];
    tube(bark, [b0, mid, top], [0.009, 0.007, 0.005], 3, (i) => i * 0.35, 0, [1.3, 2.9, 1.1]);
    const spin = R() * Math.PI * 2;
    for (let q = 0; q < petals; q++) {
      const pa = spin + (q / petals) * Math.PI * 2, tip = [top[0] + Math.cos(pa) * len, top[1] + Math.sin(pa) * len, top[2] + lift];
      tube(bark, [top, tip], [rad, rad * 0.6], 4, () => 0.7, 0, tint);
    }
    tube(bark, [add(top, [0, 0, -0.004]), add(top, [0, 0, 0.012])], [0.012, 0.01], 6, () => 0.7, 0, EYE_TINT[kind] || tint);   // the eye
  }
  return { bark, leaves };
}
/** A sapling (land-world B.sapling): a thin whip of a stem, half a metre, with a few young leaves near its top. */
export function saplingModel(seed) {
  const R = rng(seed), bark = part(), leaves = part(), h = 0.4 + R() * 0.15;
  tube(bark, [[0, 0, 0], [0.01, 0, h * 0.5], [(R() - 0.5) * 0.03, (R() - 0.5) * 0.03, h]], [0.012, 0.009, 0.005], 4, (i) => i * 0.3, 0, [1, 1, 1]);
  for (let k = 0; k < 7; k++) {
    const a = R() * Math.PI * 2, z = h * (0.45 + R() * 0.55), d = 0.04 + R() * 0.05;
    cluster(leaves, R, [Math.cos(a) * d, Math.sin(a) * d, z], 0.11 + R() * 0.05, 0, [0, 0, z], 0.5, [1, 1, 1]);
  }
  return { bark, leaves };
}
export function twigModel(seed) {
  const R = rng(seed), bark = part(), leaves = part(), ln = 0.55 + R() * 0.3;
  const pts = [0, 1, 2, 3].map((k) => [(k / 3 - 0.5) * ln, (R() - 0.5) * 0.08, 0.025 + (k === 1 || k === 2 ? 0.01 : 0)]);
  tube(bark, pts, [0.03, 0.026, 0.02, 0.014], 5, () => 0, 0, [1, 1, 1]);
  const f = pts[2], a = (R() < 0.5 ? 1 : -1) * (0.5 + R() * 0.4);
  tube(bark, [f, add(f, [Math.cos(a) * 0.2, Math.sin(a) * 0.2, 0.005]), add(f, [Math.cos(a) * 0.32, Math.sin(a) * 0.34, 0.01])], [0.016, 0.012, 0.008], 4, () => 0, 0, [1, 1, 1]);
  return { bark, leaves };
}
