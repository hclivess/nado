// A WILD WOOD'S EDGE IS FOLIAGE TO THE GROUND, NOT A PALISADE OF TRUNKS (2026-11-26, the Chlorophyll shot beside the vale:
// its woods are leaves down to the meadow; ours were a thin strip of crowns over a band of bare trunks as tall again — every
// broadleaf's lower 45 %, ADAPT.span0, which ties the drawn crown to the crown cells and so cannot move). Photographed: the
// brown share of the vale wood's lower band 7.9 % -> 2.4 %; 22 % of the far trees within the far range carry a mantle.
// Pinned (land-forest.js MANTLE):
//   1. a wild broadleaf or birch toward its wood's edge may have a mantle; deep inside, on an owned plot (wild 0), or a
//      conifer or palm, never — wilderness only, as the operator chose for tree shape;
//   2. a far tile lays the mantle out as two more crossed cards a tree (eight vertices, both faces), after the trees, and
//      still counts trees alone in `n`;
//   3. a mantle card shows the CROWN part of its tree's own picture (from the crown's base, span0 of the drawn tree, to the
//      slot's top), stands from the ground to a little over that base, and is in shade beside its tree;
//   4. it collapses onto the same root as its tree, so it goes with it at the handover to the near model.
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const F = await import(join(ROOT, "static", "land-forest.js"));
const Sp = await import(join(ROOT, "static", "land-species.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
const at = (wild, woods) => ({ wild, woods });
ok(F.mantleChance("broadleaf", at(1, 0)) === 1 && F.mantleChance("birch", at(1, 0.2)) > 0, "a wild broadleaf or birch at its wood's edge may carry a mantle");
ok(F.mantleChance("broadleaf", at(1, 0.37)) === 0 && F.mantleChance("broadleaf", at(1, 0.9)) === 0, "…never deep inside its wood, where the edge hides it");
ok(F.mantleChance("broadleaf", at(0, 0)) === 0 && F.mantleChance("birch", { woods: 0 }) === 0, "…never on an owned plot (wild 0 or unset): owned ground looks as it did");
ok(F.mantleChance("conifer", at(1, 0)) === 0 && F.mantleChance("palm", at(1, 0)) === 0, "…and only the species with a bare bole (broadleaf, birch)");
ok(F.mantleChance("broadleaf", at(1, 0.15)) > F.mantleChance("broadleaf", at(1, 0.3)), "the nearer the edge, the likelier");

// 2-4 — a real far tile in the wild around the vale
let t = null;
for (const [tu, tv] of [[195, 298], [194, 299], [196, 299], [195, 300]]) { const x = F.forestTile(0, tu, tv); if (x.n && x.mantle) { t = x; break; } }
ok(!!t, "a far tile near the vale holds trees with a mantle");
if (t) {
  const q = t.n + t.mantle;
  ok(t.pos.length === q * 24 && t.off.length === q * 24 && t.uv.length === q * 16 && t.root.length === q * 16 && t.idx.length === q * 24,
     `eight vertices (both faces indexed) for each of ${t.n} trees and ${t.mantle} mantles, the mantles after the trees`);
  const { cols, rows, tall, foot } = F.ATLAS;
  let crown = 0, low = 0, shade = 0, same = 0, seen = 0;
  // find each mantle's tree: the tree whose root (pos) is the mantle's own
  const key = (i) => [0, 1, 2].map((d) => t.pos[i * 24 + d].toFixed(3)).join();
  const treeOf = new Map();
  for (let i = 0; i < t.n; i++) treeOf.set(key(i), i);
  for (let j = t.n; j < q; j++) {
    const i = treeOf.get(key(j));
    if (i === undefined) continue;
    seen++;
    // slot row of the tree from its uv; the crown's base in the slot for that slot's (kind, height)
    const cy = Math.floor(t.uv[i * 16 + 1] * rows + 1e-6), cx = Math.floor(Math.min(t.uv[i * 16], t.uv[i * 16 + 2]) * cols + 1e-6);
    const [kind, H0] = F.SLOTS[cy * cols + cx], base = Sp.ADAPT[kind].span0 * Sp.drawnTop(kind, H0);
    const v0 = t.uv[j * 16 + 1] * rows - cy, v1 = t.uv[j * 16 + 5] * rows - cy;      // a bottom vertex, a top vertex
    if (Math.abs(v0 - (foot + base) / tall) < 1e-4 && Math.abs(v1 - 1) < 1e-4) crown++;
    const hTree = t.off[i * 24 + 6 + 0] ** 2 + t.off[i * 24 + 6 + 1] ** 2 + t.off[i * 24 + 6 + 2] ** 2;   // a top vertex's reach
    const hMant = t.off[j * 24 + 6 + 0] ** 2 + t.off[j * 24 + 6 + 1] ** 2 + t.off[j * 24 + 6 + 2] ** 2;
    if (hMant < hTree) low++;
    if (t.col[j * 24] < t.col[i * 24]) shade++;
    if (t.root[j * 16] === t.root[i * 16] && t.root[j * 16 + 1] === t.root[i * 16 + 1]) same++;
  }
  ok(seen === t.mantle, `every mantle stands on a tree's own root (${seen} of ${t.mantle})`);
  ok(crown === seen, `3. a mantle shows the crown part of its tree's own picture, from the crown's base to the top (${crown} of ${seen})`);
  ok(low === seen, `…stands lower than its tree (${low} of ${seen})`);
  ok(shade === seen, `…and is in shade beside it (${shade} of ${seen})`);
  ok(same === seen, `4. a mantle collapses onto its tree's chunk, so it goes with the tree at the handover (${same} of ${seen})`);
}
ok(F.MANTLE.over >= 1 && F.MANTLE.over <= 1.3 && F.MANTLE.shade > 0.5 && F.MANTLE.shade < 0.9, "the mantle reaches just over the crown's base, in shade but not black");

// 5. THE MANTLE, NEAR (2026-11-26): up close the tree is its model, and the far card's mantle stopped at the handover — a
// meadow grove read as a tall tree on a bare trunk. The mesher draws the same mantle from the model, for the same trees by
// the same draw: the model's leaves, squashed from the crown onto the ground to MANTLE.over of the crown's base, in
// MANTLE.shade, turned 45°, one detail level below its tree; none for a felled tree. Photographed beside a grove broadleaf
// 30 m off: a rounded mass of leaves to the ground, as the reference's meadow clumps.
{
  const { readFileSync } = await import("node:fs");
  const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
  ok(/if \(cutAt === Infinity && hash3\(gv \+ 41, gu \+ 7, face\) < mantleChance\(t\.kind, col\)\) placeMantle\(/.test(mesher),
     "5. the near model carries the mantle for exactly the trees the far card does (land-forest's draw), and a felled tree none");
  ok(/const top = ADAPT\[t\.kind\]\.span0 \* drawnTop\(t\.kind, t\.height\) \* MANTLE\.over;/.test(mesher) && /col\[i\] \*= MANTLE\.shade;/.test(mesher)
     && /treeTurn\(face, gu, gv\) \+ Math\.PI \/ 4, treeSize\(face, gu, gv, t\.kind, wildMask\(face, gu, gv\)\)/.test(mesher),
     "…its crown squashed to the ground to the far mantle's height, in its shade, turned 45° at the tree's own size");
  ok(/const far = lod >= 1 \? 2 : 1, variant/.test(mesher), "…one detail level below its tree (a broadleaf's 1,668 leaf vertices near, not 3,032)");
}
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
