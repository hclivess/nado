/*
 * test_a_plot_border_that_only_changes_colour_is_not_sampled_again.mjs — #150, measured 2026-11-16 at the second X
 * fighter's plot (the page's outline builder instrumented in a test browser): on arrival every plot's outline was sampled
 * against the ground as "titled", then sampled AGAIN as each holder's answer came back and turned it "sale" — 49 plots
 * twice, 876 ms and ~830 ms more in bursts over two seconds, for a change of colour alone. land.js updateBorders keys a
 * plot's kept outline by its shape (pieces, edits, width, which edges are drawn) and recolours it when only its kind
 * changes (borderColours). The page's updateBorders runs here with stand-ins, counting the ground samples.
 * Run: node tests/test_a_plot_border_that_only_changes_colour_is_not_sampled_again.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const fn = (name) => { const i = page.indexOf(`function ${name}(`); return page.slice(i, page.indexOf("\n}\n", i) + 2); };
const line = (start) => page.split("\n").find((l) => l.startsWith(start));
class Color { constructor(h) { this.r = ((h >> 16) & 255) / 255; this.g = ((h >> 8) & 255) / 255; this.b = (h & 255) / 255; } }
class Geo { setAttribute(k, v) { this[k] = v; } setIndex(i) { this.index = i; } dispose() {} }
const THREE = { Color, BufferGeometry: Geo, BufferAttribute: class { constructor(a) { this.array = a; } }, Mesh: class { constructor(g) { this.geometry = g; this.userData = {}; } } };
const src = [line("const BORDER = {"), line("const BORDER_R = "), line("const BORDER_W = "), "let borderMesh = null, borderOwn = \"\", borderSig = \"\", borderAt = 0;",
  "const borderCache = new Map();", fn("borderColours"), fn("updateBorders"), "return { updateBorders, borderCache, get mesh() { return borderMesh; }, reset() { borderOwn = ''; } };"].join("\n");
const X = 4999 * Wd.FACE_N + 3438, q = Wd.plotCoords(X);
const P = { face: q.face, u: q.u0 + 8, v: q.v0 + 0.5 };
const kinds = new Map();                                     // plot -> its kind, as the titles say
let samples = 0, clock = 1e9;                              // (a rebuild after a build waits 2 s)
const env = {
  THREE, Wd, P, SHOT: null, SET: { borders: true }, titles: new Map(), mine: new Set(), holderOf: () => Promise.resolve(),
  borderKind: (p) => kinds.get(p) || "titled", plotBoxes: new Map(), plotEdit: new Map(),
  earthAt: () => { samples++; return 135; }, pieceTopAt: () => -Infinity, borderMaterial: () => ({}),
  scene: { add() {}, remove() {} }, performance: { now: () => clock },
};
const B = new Function(...Object.keys(env), src)(...Object.values(env));
B.updateBorders();
const first = samples, plots = B.borderCache.size;
ok(plots === 49 && first > 49 * 100, `arriving, all ${plots} plots in view are sampled once (${first} ground samples)`);
const before = B.borderCache.get(X).pos;
for (const p of B.borderCache.keys()) kinds.set(p, "sale");   // the holders' answers come back: every plot is on sale
B.updateBorders();
ok(samples === first, `the holders' answers turn them "sale": NOT sampled again (${samples - first} more samples; were 49 plots × the whole outline)`);
const part = B.borderCache.get(X), sale = new Color(0xffd24a);
ok(part.kind === "sale" && part.pos === before && part.col[0] === Math.fround(sale.r) && part.col[1] === Math.fround(sale.g) && part.col[part.col.length - 1] === Math.fround(sale.b), "…the kept outline is recoloured to the sale colour, its shape kept as it was");
ok(B.mesh && B.mesh.geometry.color.array[0] === Math.fround(sale.r), "…and the drawn mesh carries the new colour");
env.plotBoxes.set(X, { list: [[0, 0, 0, 100, 100, 100, 1]] }); clock += 2500;
B.updateBorders();
ok(samples > first && samples - first < first / 10, `a piece placed on one plot re-samples that plot alone (${samples - first} samples)`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
