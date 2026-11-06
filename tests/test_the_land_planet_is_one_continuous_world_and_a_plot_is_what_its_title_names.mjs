/*
 * test_the_land_planet_is_one_continuous_world_and_a_plot_is_what_its_title_names.mjs — static/land-world.js, the pure
 * planet every Land client and the world server agree on:
 *   1. the numbers are land.py's: FACE_N, PLOT and PLOT_MAX match the contract, and a plot id names the same 16 x 16
 *      columns both ways (plotOf / plotCoords), the first wave is 100 distinct plots around the landing site;
 *   2. the cube-sphere is one surface: dirOf is a unit vector, gridOf inverts it on every face, a column across a face
 *      edge wraps onto the neighbouring face and the two are physically adjacent (~1 m), and blocks are ~1 m wide;
 *   3. terrain is a pure function: the same column twice is the same, terrain is continuous across a seam (no cliff
 *      from the face change alone), bedrock floors the world, and the landing site is dry land;
 *   4. a tree never straddles a plot edge (a neighbour's edit can never cut it);
 *   5. the commitment canonicalises edits (order and duplicates do not matter, the last edit of a cell wins), binds
 *      plot, salt and every edit, and refuses an edit outside the plot.
 *
 * Run: node tests/test_the_land_planet_is_one_continuous_world_and_a_plot_is_what_its_title_names.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the contract's numbers
const py = readFileSync(join(ROOT, "execnode", "games", "land.py"), "utf8");
const num = (name) => Number((py.match(new RegExp(`^${name} = (\\d+)`, "m")) || [])[1]);
ok(num("FACE_N") === Wd.FACE_N && num("PLOT") === Wd.PLOT, `FACE_N/PLOT match land.py (${num("FACE_N")}/${num("PLOT")})`);
ok(Wd.PLOT_MAX === 6 * Wd.FACE_N * Wd.FACE_N && Wd.PLOT_MAX < 2 ** 32, "PLOT_MAX = 6·FACE_N² < 2^32");
const pid = Wd.plotId(3, 100, 200), pc = Wd.plotCoords(pid);
ok(pc.face === 3 && pc.prow === 100 && pc.pcol === 200, "plotCoords inverts plotId");
ok(Wd.plotOf(3, pc.u0, pc.v0) === pid && Wd.plotOf(3, pc.u0 + 15, pc.v0 + 15) === pid && Wd.plotOf(3, pc.u0 + 16, pc.v0) !== pid,
   "a plot is exactly its 16 x 16 columns");
const wave = Wd.firstWave();
ok(wave.length === 100 && new Set(wave).size === 100 && wave.every((p) => Wd.plotCoords(p).face === Wd.SPAWN_FACE), "the first wave is 100 distinct plots on the landing face");

// 2. geometry
let worst = 0;
for (let f = 0; f < 6; f++) for (const [u, v] of [[0.5, 0.5], [Wd.W / 2, Wd.W / 3], [Wd.W - 3, 17], [12345.5, 99999.25]]) {
  const d = Wd.dirOf(f, u, v), g = Wd.gridOf(d);
  worst = Math.max(worst, Math.abs(Math.hypot(...d) - 1), g.face === f ? Math.abs(g.u - u) + Math.abs(g.v - v) : 1e9);
}
ok(worst < 1e-6, "gridOf inverts dirOf on every face (worst error " + worst.toExponential(2) + ")");
let seamWorst = 0, seamFaces = new Set();
for (let f = 0; f < 6; f++) for (const [u, v] of [[-1, Wd.W / 2], [Wd.W, Wd.W / 2], [Wd.W / 2, -1], [Wd.W / 2, Wd.W]]) {
  const w = Wd.wrap(f, u, v);
  seamFaces.add(w.face !== f);
  const inside = Wd.wrap(f, Math.min(Wd.W - 1, Math.max(0, u)), Math.min(Wd.W - 1, Math.max(0, v)));
  const a = Wd.posOf(w.face, w.u + 0.5, w.v + 0.5, 0), b = Wd.posOf(inside.face, inside.u + 0.5, inside.v + 0.5, 0);
  seamWorst = Math.max(seamWorst, Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]));
}
ok(seamFaces.size === 1 && seamFaces.has(true), "every column beyond a face edge wraps onto another face");
ok(seamWorst < 2.5, "and lands beside the edge column it continues (worst " + seamWorst.toFixed(2) + " m apart)");
const width = (f, u, v) => { const a = Wd.posOf(f, u, v, 0), b = Wd.posOf(f, u + 1, v, 0); return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); };
const wc = width(0, Wd.W / 2, Wd.W / 2), we = width(0, 10, 10);
ok(wc > 0.95 && wc < 1.05 && we > 0.6 && we < 1.45, `a block is ~1 m wide (${wc.toFixed(3)} m at a face centre, ${we.toFixed(3)} m at a corner)`);

// 3. terrain
const c1 = Wd.column(2, 70000, 70000), c2 = Wd.column(2, 70000, 70000);
ok(c1.top === c2.top && c1.biome === c2.biome, "a column is a pure function of its coordinates");
let jump = 0;
for (let f = 0; f < 6; f++) for (let t = 0; t < 40; t++) {
  const v = Math.floor((t + 0.5) * Wd.W / 40), a = Wd.column(f, Wd.W - 1, v), w = Wd.wrap(f, Wd.W, v), b = Wd.column(w.face, w.u, w.v);
  jump = Math.max(jump, Math.abs(a.top - b.top));
}
ok(jump <= 6, "terrain is continuous across face seams (worst step " + jump + " layers)");
ok(Wd.terrainBlock(1, 5, 5, 0) === Wd.B.bedrock, "bedrock floors the world");
const sp = Wd.plotCoords(Wd.plotId(Wd.SPAWN_FACE, Wd.SPAWN_PLOT_ROW + 5, Wd.SPAWN_PLOT_COL + 5));
let dry = 0;
for (const p of wave) { const q = Wd.plotCoords(p), c = Wd.column(q.face, q.u0 + 8, q.v0 + 8); if (c.top > Wd.SEA) dry++; }
ok(dry >= 90, `the landing site is dry land (${dry} of 100 first-wave plots above the sea; centre top ${Wd.column(sp.face, sp.u0 + 8, sp.v0 + 8).top})`);

// 4. trees stay inside their plot
let trees = 0, straddle = 0;
for (let u = 0; u < 400; u++) for (let v = 0; v < 400; v++) {
  const U = sp.u0 - 200 + u, V = sp.v0 - 200 + v, c = Wd.column(sp.face, U, V);
  if (Wd.treeAt(sp.face, U, V, c)) { trees++; if (Wd.plotOf(sp.face, U - 2, V - 2) !== Wd.plotOf(sp.face, U + 2, V + 2)) straddle++; }
}
ok(trees > 0 && straddle === 0, `${trees} trees near the landing site, none within 2 columns of a plot edge`);

// 5. the commitment
const salt = new Uint8Array(32).fill(7), salt2 = new Uint8Array(32).fill(8);
const E = [[1, 2, 120, Wd.B.brick], [3, 3, 121, Wd.B.glass], [1, 2, 120, Wd.B.planks]];
const ce = Wd.canonicalEdits(E);
ok(ce.length === 2 && ce[0][3] === Wd.B.planks, "the last edit of a cell wins and each cell is listed once");
const k1 = await Wd.plotCommitment(pid, salt, E), k2 = await Wd.plotCommitment(pid, salt, [E[1], E[0], E[2]]);
ok(k1 === k2, "edit order does not change the commitment");
ok(k1 !== await Wd.plotCommitment(pid + 1, salt, E), "the commitment binds the plot");
ok(k1 !== await Wd.plotCommitment(pid, salt2, E), "the commitment binds the salt");
ok(k1 !== await Wd.plotCommitment(pid, salt, [...E, [0, 0, 0, Wd.B.air]]), "the commitment binds every edit");
ok(BigInt(k1) > 0n && BigInt(k1) < 2n ** 256n, "the commitment is one non-zero 256-bit word (land.py anchor arg)");
let refused = false;
try { Wd.canonicalEdits([[16, 0, 0, 1]]); } catch (e) { refused = true; }
ok(refused, "an edit outside the plot is refused");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
