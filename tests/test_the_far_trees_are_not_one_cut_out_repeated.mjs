// The far trees are not one cut-out repeated (2026-11-22, beside the Chlorophyll shot: a row of far trees read as identical
// cards — twelve pictures, each always the same way round, their sizes within 10 %).
//   1. about half the trees show their picture mirrored (the card's u runs the other way across its atlas slot);
//   2. the crowns' widths spread over 0.85-1.15 of the picture's (times the tree's own size);
//   3. a tree's HEIGHT as a card is still the near model's: only the width and the mirror are the card's own.
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const F = await import(join(ROOT, "static", "land-forest.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
let t = null;
for (let tu = 0; tu < 400 && !(t && t.n > 40); tu++) for (let tv = 0; tv < 4 && !(t && t.n > 40); tv++) { const x = F.forestTile(0, 40 + tu, 60 + tv); if (x.n > 40) t = x; }
ok(t && t.n > 40, `a forest tile holds trees to measure (${t && t.n})`);
const { cols, wide, tall, foot } = F.ATLAS;
let mir = 0, ws = [], hs = [];
for (let i = 0; i < t.n; i++) {
  const v0 = i * 8, u0 = t.uv[v0 * 2], u1 = t.uv[(v0 + 1) * 2];          // the card's left and right corners (s = -1, +1)
  if (u0 > u1) mir++;
  const o = (k) => [t.off[k * 3], t.off[k * 3 + 1], t.off[k * 3 + 2]], d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  ws.push(d(o(v0), o(v0 + 1))); hs.push(d(o(v0), o(v0 + 2)));
}
const share = mir / t.n;
ok(share > 0.3 && share < 0.7, `about half the trees are mirrored (${(share * 100).toFixed(0)} %)`);
const ratio = ws.map((w, i) => (w / hs[i]) / (wide / tall)), lo = Math.min(...ratio), hi = Math.max(...ratio);
ok(lo >= 0.84 && hi <= 1.16 && hi - lo > 0.2, `the crowns' widths spread over ${lo.toFixed(2)}-${hi.toFixed(2)} of the picture's (0.85-1.15)`);
const hsc = hs.map((h) => h / tall);
ok(Math.min(...hsc) >= 0.899 && Math.max(...hsc) <= 1.001, `a card's height is the tree's own size, as the near model's (${Math.min(...hsc).toFixed(3)}-${Math.max(...hsc).toFixed(3)} of the picture)`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
