// land-species.js — trees GROWN from species recipes (operator 2026-11-08: "adapt the tree builder to our needs", #138).
// Pure geometry for the mesher worker: no three.js, no DOM.
//
// The recipes and the way a plant grows from one are Solstice's (https://github.com/SamG-Coder/solstice,
// crates/solstice-procgen: species/*.species and src/foliage/tree.rs), MIT licence:
//
//   Copyright (c) 2026 SamG-Coder
//   Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
//   documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
//   rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
//   permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright
//   notice and this permission notice shall be included in all copies or substantial portions of the Software.
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
//   WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
//   COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
//   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
//
// HOW IT GROWS (tree.rs): a trunk marched upward, turning a little at each step (gnarl), and LEVELS of branches, each
// spiralling round its parent at the golden angle — or in whorls, rings at one height, for a conifer — at an angle
// that changes along the parent, as long as the parent times the level's length; the trunk's own branches are as long as
// the CROWN's outline allows at their height (round, cone, even), which is what tells an oak from a fir at a glance.
// Every stem bends up (upturn) and down toward its tip (droop).
//
// WHAT IS LAND'S (adapted, not ported): Solstice grows one tree of 16,000-700,000 leaf triangles for a close view; Land
// draws hundreds at once from web workers. So
//   - a plant grows at its species' own height and is then FITTED to Land's tree: its height to the tree's cells, its
//     crown inside the tree's footprint (land-trees.js REACH) — squeezed sideways where it would reach past it;
//   - its stems are THINNED to a budget per level of detail (STEMS), its finest twigs not drawn at all;
//   - its leaves are Land's alpha-cut CARDS from the painted atlas (land-trees.js card), set along its outermost shoots
//     as Solstice sets leaves, to a budget (ADAPT.cards) — a needle spray along each conifer shoot;
//   - its crown starts where Land's crown cells do (ADAPT.span0), so chopping a crown cell takes what is drawn in it.

// ---- the recipes, verbatim from Solstice -------------------------------------------------------------------------------
export const RECIPES = {
  oak: `# A young oak grown in the open: a short, flared trunk and a broad, rounded crown of
# crooked limbs, the lower ones spreading wide.
height 11
trunk radius=0.24 flare=0.6 gnarl=0.05
crown round
bark oak_bark
level per_metre=4.2 span=0.28..0.97 angle=72..44 length=0.5 radius=0.55 upturn=0.12 droop=0.05 gnarl=0.25
level per_metre=2.6 span=0.15..0.95 angle=42 length=0.42 radius=0.6 upturn=0.25 droop=0.1 gnarl=0.4
level per_metre=8 span=0.2..1 angle=48 length=0.35 radius=0.6 upturn=0.3 droop=0.2 gnarl=0.6
leaves broadleaf_leaves per_metre=42 length=0.08..0.13 width=0.55 variants=0.4,0.3,0.2,0.1 normals=0.45`,
  birch: `# A silver birch: a tall, slender white trunk, steep limbs, and fine twigs that hang down.
height 14
trunk radius=0.15 flare=0.3 gnarl=0.06
crown round
bark birch_bark
level per_metre=3.4 span=0.35..0.98 angle=56..28 length=0.36 radius=0.5 upturn=0.22 droop=0.05 gnarl=0.3
level per_metre=3 span=0.2..0.95 angle=45 length=0.5 radius=0.5 droop=0.45 gnarl=0.4
# The hanging twigs that carry the leaves.
level per_metre=7 span=0.2..1 angle=30 length=0.4 radius=0.6 droop=0.6 gnarl=0.5
leaves birch_leaves per_metre=34 length=0.045..0.07 width=0.7 variants=0.35,0.35,0.22,0.08 normals=0.5`,
  fir: `# A fir: a straight trunk to the very top, carrying whorls of level branches that droop at
# their ends, in a narrow cone.
height 16
trunk radius=0.22 flare=0.45 gnarl=0.015
crown cone
bark fir_bark
# Whorls of five about 60 cm apart, so the crown reads as one cone rather than tiers.
level per_metre=8 span=0.1..0.99 angle=102..74 length=0.2 radius=0.4 upturn=0.08 droop=0.3 gnarl=0.12 whorl=5
# Side shoots, flattened into sprays either side of the branch.
level per_metre=10 span=0.05..0.97 angle=62 length=0.4 radius=0.55 upturn=0.04 droop=0.12 gnarl=0.25
# For needles, width is each needle's length as a fraction of its shoot's.
leaves fir_needles per_metre=22 length=0.16..0.26 width=0.17 variants=0.35,0.3,0.25,0.1 normals=0.4`,
  bush: `# A dense bush of many stems from the ground.
height 0.25
trunk radius=0.05 flare=0.2 gnarl=0.1
crown even
bark beech_bark
level per_metre=64 span=0..1 angle=58..30 length=6 radius=0.55 upturn=0.15 droop=0.35 gnarl=0.6
level per_metre=12 span=0.2..1 angle=45 length=0.35 radius=0.6 upturn=0.4 droop=0.2 gnarl=0.8
leaves broadleaf_leaves per_metre=55 length=0.04..0.065 width=0.6 variants=0.3,0.4,0.3,0 normals=0.55`,
};

/** A recipe's text as numbers (Solstice's species.rs format: one `key value…` line each, `level`s in order). */
export function parseSpecies(text) {
  const sp = { height: 1, trunk: { radius: 0.2, flare: 0, gnarl: 0 }, crown: "round", levels: [] };
  const kv = (words) => Object.fromEntries(words.map((w) => w.split("=")));
  const range = (s) => { const [a, b] = String(s).split(".."); return [Number(a), Number(b === undefined ? a : b)]; };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const [key, ...rest] = line.split(/\s+/);
    if (key === "height") sp.height = Number(rest[0]);
    else if (key === "crown") sp.crown = rest[0];
    else if (key === "trunk") { const o = kv(rest); sp.trunk = { radius: Number(o.radius), flare: Number(o.flare || 0), gnarl: Number(o.gnarl || 0) }; }
    else if (key === "level") {
      const o = kv(rest);
      sp.levels.push({ perMetre: Number(o.per_metre ?? 4), span: range(o.span ?? "0..1"), angle: range(o.angle ?? "45"), length: Number(o.length ?? 0.5),
                       taper: Number(o.taper ?? 0.5), radius: Number(o.radius ?? 0.6), upturn: Number(o.upturn ?? 0), droop: Number(o.droop ?? 0),
                       gnarl: Number(o.gnarl ?? 0.3), whorl: Number(o.whorl ?? 0) });
    }
  }
  return sp;
}

// ---- Land's adaptation, per Land tree kind ---------------------------------------------------------------------------
//   recipe   the Solstice species it grows from
//   top      where the drawn crown tops out, in m above the tree's ground, for cell height H0 (it reaches H0 + 1)
//   span0    where the trunk's branches start, as a fraction of the trunk — Land's crown cells (land-world treeCell)
//   card     a leaf card's size range (m) and atlas tile (land-trees.js LEAF_TILE); the tree's cards are shared out over
//            its outermost shoots by their length
//   girth    trunk radius in m (Land's trunks are drawn a little stouter than a sapling-thin scale would leave them)
//   cards    leaf cards per tree, near and far
//   segs     rings along every branch, where a species needs fewer (a fir's hundred straight whorl branches)
//   sprays   leaves as needle sprays laid end to end along the outermost stems
//   wood     the deepest level drawn as wood, near and far (0 the trunk alone, -1 none): a conifer's side shoots are its
//            needle sprays and far away its whorls are too; a bush's stems are its leaves' business at a distance
//   stems    how many stems each level may grow, near ([limbs, branches, twigs]) and far ([limbs]: far away a tree is its
//            trunk, its limbs and their leaves) — each level its own budget, so the outermost shoots that carry the
//            leaves are never starved by the levels inside them
export const ADAPT = {
  broadleaf: { recipe: "oak", top: (H0) => H0 + 1.3, span0: 0.45, card: [0.85, 1.3], tile: 0, girth: 0.3,
               stems: { 0: [9, 26, 70], 2: [8] }, cards: { 0: 230, 2: 80 }, wood: [2, 1] },
  birch: { recipe: "birch", top: (H0) => H0 + 1.3, span0: 0.4, card: [0.55, 0.85], tile: 1, girth: 0.16,
           stems: { 0: [11, 30, 70], 2: [10] }, cards: { 0: 200, 2: 80 }, wood: [2, 1] },
  // a fir's needles cover its whorl branches end to end (sprays along each branch, as a fir reads from afar); its side
  // shoots are not grown — on their own they were tiny cards on bare poles
  conifer: { recipe: "fir", top: (H0) => H0 + 1.6, span0: 0.22, card: [0.34, 0.55], tile: 2, girth: 0.28,
             // #150: the middle level keeps 70 of the 100 limbs and 110 of the 120 needle sprays — its needles still sit on
             // wood and its crown stays full (photographed beside the near and far models: 60 limbs and the default 88
             // sprays read sparse at the top). Its far depth, the bare trunk, is too bare beside a player on Low, where
             // level 1 is the nearest level drawn. Bark is the cost (1,260 triangles at 100 limbs); a spray is cheap.
             stems: { 0: [100], 1: [70], 2: [48] }, cards: { 0: 120, 1: 110, 2: 56 }, wood: [1, 0], sprays: true, segs: 2 },
  bush: { recipe: "bush", top: () => 1.15, span0: 0, card: [0.5, 0.8], tile: 0, girth: 0.03,
          stems: { 0: [22, 40], 2: [16] }, cards: { 0: 60, 2: 24 }, wood: [1, -1] },
};

const GOLDEN = 2.399963;
const ENVELOPE = {
  round: (x) => Math.pow(Math.sin(Math.PI * (x * 0.85 + 0.12)), 0.7),
  cone: (x) => 1 - x * 0.85,
  even: (x) => 1 - x * 0.3,
};
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
/** A unit vector perpendicular to `axis`, turned `angle` round it (tree.rs perpendicular; z is up here, y there). */
function perpendicular(axis, angle) {
  const ref = Math.abs(axis[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0], f = norm(cross(axis, ref)), g = cross(axis, f);
  return add(mul(f, Math.cos(angle)), mul(g, Math.sin(angle)));
}
/** One stem, marched along and turning a little at each step (tree.rs grow), coarser than Solstice's for a crowd. */
function grow(R, start, dir, length, radius, tip, lv, maxSegs) {
  const spacing = Math.min(Math.max(radius * 10, 0.35), 1.2, length / 2);
  const segs = Math.max(2, Math.min(maxSegs, Math.ceil(length / spacing))), step = length / segs;
  const pts = [start], radii = [radius];
  let d = norm(dir), p = start;
  for (let i = 1; i <= segs; i++) {
    const t = i / segs, s = () => R() * 2 - 1;
    const wander = [s() * lv.gnarl, s() * lv.gnarl, s() * lv.gnarl * 0.5];
    d = norm(add(d, mul(add(wander, [0, 0, lv.upturn - lv.droop * t * 2]), step)));
    p = add(p, mul(d, step));
    pts.push(p); radii.push(radius + (tip - radius) * Math.pow(t, 0.8));
  }
  return { pts, radii, len: length };
}
export function at(stem, t) {
  const n = stem.pts.length - 1, x = Math.min(Math.max(t, 0), 1) * n, i = Math.min(Math.floor(x), n - 1), f = x - i;
  const a = stem.pts[i], b = stem.pts[i + 1];
  return { p: add(a, mul(sub(b, a), f)), d: norm(sub(b, a)), r: stem.radii[i] + (stem.radii[i + 1] - stem.radii[i]) * f };
}
/** Where shoots leave their parent (tree.rs shoot_positions): [fraction along, angle around] for each. */
function shoots(R, lv, count) {
  const span = lv.span[1] - lv.span[0], out = [];
  if (lv.whorl > 0) {
    const rings = Math.max(1, Math.ceil(count / lv.whorl));
    for (let ring = 0; ring < rings; ring++) {
      const t = lv.span[0] + span * (ring + 0.35 + R() * 0.3) / rings, start = R() * Math.PI * 2;
      for (let k = 0; k < lv.whorl; k++) out.push([t + (R() * 2 - 1) * 0.004, start + (k + (R() * 2 - 1) * 0.15) / lv.whorl * Math.PI * 2]);
    }
  } else {
    let spin = R() * Math.PI * 2;
    for (let k = 0; k < count; k++) { spin += GOLDEN; out.push([lv.span[0] + span * (k + 0.2 + R() * 0.6) / count, spin]); }
  }
  return out;
}

/** A plant of Land tree `kind` (cells H0 high), grown from its recipe and fitted to Land: { stems: [{ pts, radii, len,
 *  depth }], leafy: [stem index], centre } in metres, z up, the root at the origin. lod 2 grows fewer, coarser stems. */
export function growPlant(kind, H0, R, lod) {
  const A = ADAPT[kind], sp = parseSpecies(RECIPES[A.recipe]), far = lod >= 2;
  const levels = sp.levels.map((lv, i) => (i === 0 && A.span0 ? { ...lv, span: [Math.max(lv.span[0], A.span0), lv.span[1]] } : lv));
  const lean = [(R() * 2 - 1) * 0.05, (R() * 2 - 1) * 0.05, 0];
  const trunk = grow(R, [0, 0, -sp.trunk.radius], add([0, 0, 1], lean), sp.height + sp.trunk.radius, sp.trunk.radius, sp.trunk.radius * 0.25,
                     { upturn: 0.02, droop: 0, gnarl: sp.trunk.gnarl }, far ? 4 : 6);
  const stems = [{ ...trunk, depth: 0 }];
  let gen = [0];
  const caps = A.stems[far ? 2 : lod === 1 && A.stems[1] ? 1 : 0];   // a kind may give its middle level a budget of its own (#150: the conifer)
  levels.slice(0, caps.length).forEach((lv, depth) => {
    // how many this level would have, all parents together — thinned evenly to its budget
    const span = lv.span[1] - lv.span[0];
    const want = gen.reduce((n, pi) => n + Math.max(1, Math.round(stems[pi].len * span * lv.perMetre)), 0);
    const keep = Math.min(1, caps[depth] / want);
    const next = [];
    for (const pi of gen) {
      const parent = stems[pi], count = Math.max(1, Math.round(parent.len * span * lv.perMetre));
      for (const [t, spin] of shoots(R, lv, count)) {
        if (R() >= keep) continue;
        const { p, d, r } = at(parent, t), side = perpendicular(d, spin);
        const along = Math.min(1, Math.max(0, (t - lv.span[0]) / Math.max(span, 1e-6)));
        const angle = ((lv.angle[0] + (lv.angle[1] - lv.angle[0]) * along + (R() * 2 - 1) * 10) * Math.PI) / 180;
        let len = parent.len * lv.length * (0.75 + R() * 0.45);
        len *= depth === 0 ? ENVELOPE[sp.crown](along) : 1 - lv.taper * along;
        if (len < 0.05) continue;
        const rad = Math.max(r * lv.radius, 0.003);
        // rings along a stem by its depth (limbs 4, branches 3, twigs 2): a crowd of trees, not one close up
        const s = grow(R, p, add(mul(d, Math.cos(angle)), mul(side, Math.sin(angle))), len, rad, Math.max(rad * 0.2, 0.0015), lv,
                       A.segs || (far ? 3 : [4, 3, 2][depth] || 2));
        next.push(stems.length);
        stems.push({ ...s, depth: depth + 1 });
      }
    }
    if (next.length) gen = next;
  });
  // FIT TO LAND: the plant's top to the tree's (its cells end at H0 + 1), its crown inside the footprint; radii follow the
  // height's scale, the trunk to Land's girth
  let top = 0, reach = 0;
  for (const s of stems) for (const q of s.pts) { top = Math.max(top, q[2]); reach = Math.max(reach, Math.hypot(q[0], q[1])); }
  const sz = A.top(H0) / top, sxy = Math.min(sz, (0.92 * 2.45) / Math.max(reach, 1e-6)), girth = A.girth / (sp.trunk.radius * sz);
  for (const s of stems) {
    s.pts = s.pts.map((q) => [q[0] * sxy, q[1] * sxy, q[2] * sz]);
    s.radii = s.radii.map((r) => r * sz * girth);
    s.len *= sz;
  }
  let c = [0, 0, 0], n = 0;
  for (const i of gen) for (const q of stems[i].pts) { c = add(c, q); n++; }
  return { stems, leafy: gen, centre: n ? mul(c, 1 / n) : [0, 0, A.top(H0) * 0.7] };
}
