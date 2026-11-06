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
// A model is a function of (kind, height, seed, lod) — the same tree on every screen. Local axes: x east, y north, z up,
// metres from the root at ground level. Every model stays inside its tree's cells' footprint (2 columns around the root,
// TREE_REACH above), so no tree is drawn over a neighbouring plot.
//
// Leaf atlas: 2 x 2 tiles, (t & 1, t >> 1) — 0 broadleaf cluster, 1 birch cluster, 2 needle spray (twig along v),
// 3 palm frond (rachis along v). Bark: tile 0 bark, 1 birch (static/land.js picks the texture).
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

/** { bark, leaves } for a tree: kind and height as land-world treeAt gives them, seed from its root, lod 0..2. */
export function treeModel(kind, height, seed, lod = 0) {
  const R = rng(seed), bark = part(), leaves = part();
  const far = lod >= 2, sides = far ? 4 : 7, keep = far ? 0.5 : 1, grow = far ? 1.35 : 1;   // far: half the cards, larger
  const takeCard = () => keep >= 1 || R() < keep;
  const brown = [1, 1, 1], H0 = height;
  if (kind === "broadleaf") {
    const top = H0 * 0.55, ccen = [0, 0, H0 + 0.3], lean = [(R() - 0.5) * 0.3, (R() - 0.5) * 0.3, 0];
    const tr = [[0, 0, -0.3], [0, 0, 0.15], add([0, 0, top * 0.5], mul(lean, 0.5)), add([0, 0, top], lean), add([0, 0, H0 + 0.8], lean)];
    tube(bark, tr, [0.34, 0.25, 0.2, 0.16, 0.06], sides, (i) => 0.02 * (i / 4) ** 2, 0, brown);
    const n = 4 + Math.floor(R() * 2);
    for (let l = 0; l < n; l++) {
      const az = (l / n) * Math.PI * 2 + R() * 0.8, el = 0.6 + R() * 0.45, ln = 1.5 + R() * 0.6;
      const p0 = add([0, 0, top - R() * 0.4], lean), pts = limb(p0, dirAt(az, el), ln, -0.12, 3);
      tube(bark, pts, [0.11, 0.08, 0.06, 0.04], Math.max(3, sides - 2), (i) => 0.03 + 0.04 * i / 3, 0, brown);
      for (let t = 0; t < 3; t++) {
        const from = pts[1 + Math.floor(R() * 3)], tz = az + (R() - 0.5) * 1.8, tw = limb(from, dirAt(tz, 0.2 + R() * 0.7), 0.6 + R() * 0.5, -0.3, 2);
        if (!far) tube(bark, tw, [0.035, 0.022, 0.012], 4, () => 0.09, 0, brown);
        for (let k = 0; k < 9; k++) if (takeCard()) {
          const c = add(tw[2], [(R() - 0.5) * 1.3, (R() - 0.5) * 1.3, (R() - 0.3) * 0.9]);
          cluster(leaves, R, c, (1.05 + R() * 0.5) * grow, 0, ccen, 0.14 + 0.06 * R(), tintOf(R, [1, 1, 1], 0.3));
        }
      }
    }
    for (let k = 0; k < 22; k++) if (takeCard())                // the crown's top and heart, so no gap shows the sky
      cluster(leaves, R, add(ccen, [(R() - 0.5) * 2.2, (R() - 0.5) * 2.2, (R() - 0.2) * 1.4]), 1.2 * grow, 0, ccen, 0.12, tintOf(R, [1, 1, 1], 0.3));
  } else if (kind === "birch") {
    const top = H0 + 1.2, bend = [(R() - 0.5) * 0.5, (R() - 0.5) * 0.5, 0];
    const tr = [0, 0.25, 0.5, 0.75, 1].map((f) => add([0, 0, -0.3 + f * (top + 0.3)], mul(bend, f * f)));
    tube(bark, tr, [0.17, 0.13, 0.11, 0.08, 0.03], sides, (i) => 0.03 * (i / 4) ** 2, 1, brown);
    const ccen = add([0, 0, H0 - 0.2], mul(bend, 0.7));
    const nb = far ? 6 : 10;
    for (let l = 0; l < nb; l++) {
      const f = 0.42 + 0.55 * (l / nb), p0 = add([0, 0, f * top], mul(bend, f * f)), az = l * 2.4 + R() * 0.5;
      const pts = limb(p0, dirAt(az, 0.7 + R() * 0.4), 0.7 + (1 - f) * 1.4 + R() * 0.3, -0.35, 3);
      tube(bark, pts, [0.04, 0.03, 0.02, 0.01], 4, (i) => 0.05 + 0.05 * i / 3, 1, brown);
      for (let k = 0; k < 8; k++) if (takeCard()) {
        const c = add(pts[1 + Math.floor(R() * 3)], [(R() - 0.5) * 0.7, (R() - 0.5) * 0.7, -0.15 - R() * 0.45]);   // hanging
        cluster(leaves, R, c, (0.7 + R() * 0.3) * grow, 1, ccen, 0.18 + 0.08 * R(), tintOf(R, [1, 1, 1], 0.25));
      }
    }
  } else if (kind === "conifer") {
    const top = H0 + 1.6, z0 = 2.0;
    tube(bark, [[0, 0, -0.3], [0, 0, 0.3], [0, 0, top * 0.5], [0, 0, top]], [0.3, 0.24, 0.15, 0.03], sides, (i) => 0.015 * (i / 3) ** 2, 0, brown);
    const step = far ? 0.7 : 0.42;
    for (let z = z0, w = 0; z < top - 0.25; z += step * (0.85 + R() * 0.3), w++) {
      const f = (z - z0) / (top - z0), ln = 0.35 + (1 - f) * 1.95, nb = far ? 4 : 5 + (R() < 0.5 ? 1 : 0);
      for (let l = 0; l < nb; l++) {
        const az = (l / nb) * Math.PI * 2 + w * 0.7 + R() * 0.4, el = 0.12 - 0.25 * (1 - f) + (R() - 0.5) * 0.15;
        const pts = limb([0, 0, z], dirAt(az, el), ln, -0.18, 2);
        if (!far) tube(bark, pts, [0.035, 0.022, 0.01], 3, (i) => 0.04 + 0.05 * i / 2, 0, brown);
        // the needles: two cards along the branch, one flat and one tilted, the spray's twig along their v axis
        const mid = mul(add(pts[0], pts[2]), 0.5), along = mul(sub(pts[2], pts[0]), 0.55);
        const side = norm(cross(along, [0, 0, 1])), wdt = 0.28 + 0.22 * (1 - f);
        const out = add(sub(mid, [0, 0, z]), [0, 0, 0.2]);
        const tint = tintOf(R, [1, 1, 1], 0.2);
        card(leaves, mid, mul(side, wdt * grow), along, 2, out, 0.12 + 0.1 * (ln / 2.3), tint);
        if (!far) card(leaves, add(mid, [0, 0, 0.04]), mul(norm(add(mul(side, 0.5), [0, 0, 0.85])), wdt * 0.8), along, 2, out, 0.12 + 0.1 * (ln / 2.3), tint);
      }
    }
    if (takeCard()) cluster(leaves, R, [0, 0, top - 0.1], 0.7, 2, [0, 0, top - 1], 0.1, [1, 1, 1]);   // the leader's tip
  } else if (kind === "palm") {
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
  } else if (kind === "bush") {
    const ccen = [0, 0, 0.55];
    for (let l = 0; l < (far ? 0 : 4); l++) tube(bark, limb([0, 0, -0.1], dirAt(R() * 6.28, 1.0 + R() * 0.3), 0.7, -0.2, 2), [0.03, 0.02, 0.01], 3, () => 0.05, 0, brown);
    const nc = far ? 14 : 34;
    for (let k = 0; k < nc; k++) {
      const a = R() * Math.PI * 2, r = Math.sqrt(R()) * 0.95, c = [Math.cos(a) * r, Math.sin(a) * r, 0.25 + R() * 0.75 * (1 - r * 0.5)];
      cluster(leaves, R, c, (0.6 + R() * 0.3) * grow, 0, ccen, 0.08 + 0.05 * R(), tintOf(R, [0.95, 1, 0.9], 0.25));
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
export function twigModel(seed) {
  const R = rng(seed), bark = part(), leaves = part(), ln = 0.55 + R() * 0.3;
  const pts = [0, 1, 2, 3].map((k) => [(k / 3 - 0.5) * ln, (R() - 0.5) * 0.08, 0.025 + (k === 1 || k === 2 ? 0.01 : 0)]);
  tube(bark, pts, [0.03, 0.026, 0.02, 0.014], 5, () => 0, 0, [1, 1, 1]);
  const f = pts[2], a = (R() < 0.5 ? 1 : -1) * (0.5 + R() * 0.4);
  tube(bark, [f, add(f, [Math.cos(a) * 0.2, Math.sin(a) * 0.2, 0.005]), add(f, [Math.cos(a) * 0.32, Math.sin(a) * 0.34, 0.01])], [0.016, 0.012, 0.008], 4, () => 0, 0, [1, 1, 1]);
  return { bark, leaves };
}
