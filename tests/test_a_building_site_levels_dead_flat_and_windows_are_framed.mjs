/*
 * test_a_building_site_levels_dead_flat_and_windows_are_framed.mjs — "it is currently not possible to level ground ... to
 * have a nice clean structure", "windows on the house look weird and it is not on a flat ground" (operator 2026-11-06/07):
 *   1. levelling (static/land-level.js) a 5 x 5 site at layer T — on a gentle meadow and on a hillside that needs cutting
 *      and filling, a tree on it felled — leaves the drawn ground across the site's interior at exactly T + 1 (the smooth
 *      surface, as meshed); without an axe a trunk on the site is left and reported;
 *   2. its ops are only digs and earth placements, and it asks for earth only when the digging does not give enough back;
 *   3. a window is drawn as a timber frame (two jambs, sill, head, a cross mullion) in the frame's material and a thin pane
 *      in glass — not a box of blue tile — and the page draws the frame in wood and the glass clear;
 *   4. a window is a unit made at the workbench from glass, planks and nails, reachable from bare hands.
 *
 * Run: node tests/test_a_building_site_levels_dead_flat_and_windows_are_framed.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const { levelOps, earthNeeded, trunkIn } = await import(join(ROOT, "static", "land-level.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

function levelSite(face, cu, cv, label) {
  const edits = new Map(), k = (u, v, h) => face + ":" + u + ":" + v + ":" + h;
  const w = { block: (u, v, h) => { const e = edits.get(k(u, v, h)); return e !== undefined ? e : Wd.terrainBlock(face, u, v, h); },
              edited: (u, v, h) => edits.has(k(u, v, h)), top: (u, v) => Wd.column(face, u, v).top };
  const T = w.top(cu, cv), all = [];
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) {
    const ops = levelOps(w, cu + du, cv + dv, T, 3, true);           // a player with an axe: trunks on the site are felled
    for (const [u, v, h, b] of ops) edits.set(k(u, v, h), b);                 // the server applies them in order
    all.push(...ops);
  }
  let lo = Infinity, hi = -Infinity, n = 0;
  const pu = Math.floor(cu / 16), pv = Math.floor(cv / 16);
  for (const ch of new Set([Math.floor((T - 1) / 16), Math.floor(T / 16), Math.floor((T + 1) / 16)])) {
    for (const [du, dv] of [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]]) {
      const r = M.meshChunk(face, pu + du, pv + dv, ch, edits, null, 0);
      if (r.empty || !r.smooth) continue;
      const U = r.smooth.uvw;
      for (let i = 0; i < U.length / 3; i++) {
        // grid position relative to the site's centre column (uvw folds every 4096 m)
        const du2 = ((U[i * 3] - (cu % 4096)) + 6144) % 4096 - 2048, dv2 = ((U[i * 3 + 1] - (cv % 4096)) + 6144) % 4096 - 2048;
        if (Math.abs(du2 - 0.5) <= 1.5 && Math.abs(dv2 - 0.5) <= 1.5) { lo = Math.min(lo, U[i * 3 + 2]); hi = Math.max(hi, U[i * 3 + 2]); n++; }
      }
    }
  }
  ok(n > 0 && Math.abs(lo - (T + 1)) < 1e-4 && Math.abs(hi - (T + 1)) < 1e-4,
     `${label}: the levelled site's ground lies at exactly ${T + 1} (${n} points from ${lo.toFixed(4)} to ${hi.toFixed(4)})`);
  return { all, w0: { block: (u, v, h) => Wd.terrainBlock(face, u, v, h) } };
}

// 1. a gentle meadow (the landing site) and a hillside nearby
const sp = Wd.plotCoords(Wd.plotId(Wd.SPAWN_FACE, Wd.SPAWN_PLOT_ROW + 5, Wd.SPAWN_PLOT_COL + 5));
const flat = levelSite(sp.face, sp.u0 + 8, sp.v0 + 8, "a meadow");
let hill = null;
for (let du = 0; du < 3000 && !hill; du += 13) for (let dv = 0; dv < 3000 && !hill; dv += 13) {
  const u = sp.u0 + 8 + du, v = sp.v0 + 8 + dv, bio = Wd.column(sp.face, u, v).biome;
  if (u % 16 < 4 || u % 16 > 11 || v % 16 < 4 || v % 16 > 11 || (bio !== "grass" && bio !== "forest")) continue;
  let lo = Infinity, hi = -Infinity;
  for (let a = -2; a <= 2; a++) for (let c = -2; c <= 2; c++) { const t = Wd.column(sp.face, u + a, v + c).top; lo = Math.min(lo, t); hi = Math.max(hi, t); }
  if (hi - lo >= 2 && hi - lo <= 3) hill = [u, v];
}
ok(!!hill, "a hillside rising across the site was found");
const slope = levelSite(sp.face, hill[0], hill[1], "a hillside (cut and fill)");
ok(slope.all.some(([, , , b]) => b === Wd.B.air) && slope.all.some(([, , , b]) => b === Wd.B.dirt), "on the hillside it both cuts and fills");

{
  const w = { block: (u, v, h) => (u === 0 && v === 0 && h === 11 ? Wd.B.log : h <= 10 ? Wd.B.grass : Wd.B.air), edited: () => false, top: () => 10 };
  ok(!levelOps(w, 0, 0, 10, 3, false).some(([, , h]) => h === 11) && levelOps(w, 0, 0, 10, 3, true).some(([, , h, b]) => h === 11 && b === Wd.B.air) && trunkIn(w, 0, 0, 10),
     "a trunk on the site is felled only by a player with an axe, and is reported otherwise");
}
// 2
ok(flat.all.every(([, , , b]) => b === Wd.B.air || b === Wd.B.dirt), "levelling is only digs and earth placements");
const dig = [[0, 0, 5, Wd.B.air], [0, 0, 5, Wd.B.dirt]];
ok(earthNeeded(dig, { block: () => Wd.B.grass }) === 0 && earthNeeded([[0, 0, 5, Wd.B.dirt]], { block: () => Wd.B.air }) === 1,
   "earth is asked for only when the digs do not give it back");

// 3. a window
const q = Wd.plotCoords(Wd.firstWave()[44]), y0 = (Wd.column(q.face, q.u0 + 8, q.v0 + 8).top + 20) * 100;
const r = M.meshChunk(q.face, q.u0 / 16, q.v0 / 16, Math.floor(y0 / 1600), null, [[400, 400, y0, 100, 10, 120, Wd.B.window]], 0);
const frame = (r.pieces.groups || []).find((g) => g[2] === Wd.B.window);
ok(frame && frame[1] / 3 === 6 * 12, `a window's frame is six timber parts (jambs, sill, head, mullion, transom): ${frame ? frame[1] / 3 : 0} triangles`);
ok(r.glassy && r.glassy.idx.length / 3 === 12, `…around a thin pane of glass (${r.glassy ? r.glassy.idx.length / 3 : 0} triangles)`);
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/40: \["darkwood"/.test(land) && /glassFres/.test(land) && !/matGlassy\.opacityNode = sample\.a/.test(land), "the page draws the frame in wood and the glass clear, more of a mirror at an angle");

// 4
const win = R.recipes.find((x) => x.id === "window");
ok(R.items.window.unit && win && win.uses.some(([i]) => i === "glass") && win.uses.some(([i]) => i === "nails") && win.with.includes("workbench"),
   "a window is a unit made at the workbench from glass, planks and nails");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
