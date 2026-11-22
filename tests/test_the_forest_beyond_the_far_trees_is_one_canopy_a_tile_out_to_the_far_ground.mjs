/*
 * test_the_forest_beyond_the_far_trees_is_one_canopy_a_tile_out_to_the_far_ground.mjs — the Chlorophyll bar (operator
 * 2026-11-21: a meadow under hills covered in forest; "keep going until you match the graphical fidelity"). Past the card
 * trees (forestRange, 1.15 km) the hills were bare to the far ground's edge. land-forest.js canopyTile draws a forest
 * tile there as ONE heightfield, as that engine draws a far tile "as one aggregate":
 *   1. where the planet's forest field says forest the canopy stands at its climate's crown height (canopyHeight: the
 *      species treeAt grows there), thinner toward the edge; out of the forest it sinks under the ground, so a forest's
 *      edge is a wall down to the meadow; meadow, sea and desert make none; every triangle faces the sky;
 *   2. it is cheap: one tile in a few tens of ms, a few hundred cells — against the tens of thousands of card trees the
 *      same land would be;
 *   3. the page asks the mesher workers for canopy tiles in the band from the card trees' reach to CANOPY_RANGE, draws
 *      none inside that reach (canopyIn), routes the results, places the meshes and drops the tiles it leaves behind.
 * Run: node tests/test_the_forest_beyond_the_far_trees_is_one_canopy_a_tile_out_to_the_far_ground.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), F = await import(join(ROOT, "static", "land-forest.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the field decides
const fake = (o) => Object.assign({ top: W.SEA + 20, height: W.SEA + 20, biome: "forest", temp: 0.2, wet: 0.1, woods: 0.5 }, o);
ok(F.canopyHeight(fake({ biome: "grass" })) === 0 && F.canopyHeight(fake({ biome: "desert" })) === 0 && F.canopyHeight(fake({ top: W.SEA })) === 0,
  "meadow, desert and the sea grow no canopy");
const mild = F.canopyHeight(fake({})), cold = F.canopyHeight(fake({ temp: -0.5 })), edge = F.canopyHeight(fake({ woods: 0.13 }));
ok(mild > 3 && cold > mild && edge < mild && edge > 0, `a forest's canopy stands at its climate's crown height — mild ${mild.toFixed(1)} m, cold (conifers) ${cold.toFixed(1)} m — and lower at its edge (${edge.toFixed(1)} m)`);
let tile = null, tu, tv;
const T = F.CANOPY_TILE, N = T / F.CANOPY_STEP, ALL = N * N;
for (tu = 52; tu < 56 && !(tile && tile.n > 50 && tile.n < ALL); tu++) for (tv = 76; tv < 80; tv++) { tile = F.canopyTile(0, tu, tv); if (tile.n > 50 && tile.n < ALL) break; }
tu--;
ok(T === 1024 && tile && tile.n > 50 && tile.n < ALL, `a 1,024 m tile at a forest's edge draws its forest cells only (${tile && tile.n} of ${ALL}) — one mesh, one draw, for sixteen forest tiles' land`);
const anchor = tile.anchor, up = W.frameOf(0, tu * T + T / 2, tv * T + T / 2).up;
let above = 0, below = 0, upF = 0, downF = 0;
for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
  const k = j * (N + 1) + i, u = tu * T + i * F.CANOPY_STEP, v = tv * T + j * F.CANOPY_STEP, w = W.wrap(0, u, v), c = W.column(w.face, w.u, w.v);
  const p = [tile.pos[k * 3] + anchor[0], tile.pos[k * 3 + 1] + anchor[1], tile.pos[k * 3 + 2] + anchor[2]], g = W.posOf(0, u, v, c.height);
  const h = (p[0] - g[0]) * up[0] + (p[1] - g[1]) * up[1] + (p[2] - g[2]) * up[2];
  if (F.canopyHeight(c) > 0) { if (h > 2) above++; } else if (h < -1) below++;
}
ok(above > 50 && below > 50, `forest vertices stand over the ground (${above}), the rest sink under it (${below}) — the forest's edge is a wall`);
for (let t = 0; t < tile.idx.length; t += 3) {
  const [a, b, c] = [tile.idx[t], tile.idx[t + 1], tile.idx[t + 2]].map((i) => [tile.pos[i * 3], tile.pos[i * 3 + 1], tile.pos[i * 3 + 2]]);
  const e = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], f = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n = [e[1] * f[2] - e[2] * f[1], e[2] * f[0] - e[0] * f[2], e[0] * f[1] - e[1] * f[0]];
  if (n[0] * up[0] + n[1] * up[1] + n[2] * up[2] > 0) upF++; else downF++;
}
ok(upF > 0 && downF === 0, `every triangle faces the sky (${upF} up, ${downF} down)`);
// 2. cheap
const t0 = performance.now(); let cells = 0;
for (let a = 0; a < 4; a++) cells += F.canopyTile(0, 53 + (a % 2), 77 + Math.floor(a / 2)).n;
const ms = (performance.now() - t0) / 4;
ok(ms < 1500 && cells / 4 <= ALL, `a 1,024 m tile in ${ms.toFixed(0)} ms in a worker, ${Math.round(cells / 4)} cells (two triangles each) on average`);
// 3. the page
ok(mesher.includes("if (m.canopy) {") && mesher.includes("res = canopyTile(m.face, m.tu, m.tv);") && mesher.indexOf("if (m.canopy) {") < mesher.indexOf("if (m.forest) {"),
  "the mesher workers build canopy tiles (asked before the forest's own jobs are read)");
ok(/const CANOPY_RANGE = PHONE \? \d+ : \d+;/.test(page) && page.includes("const T = Forest.CANOPY_TILE, face = P.face") && page.includes("fu * fu + fv * fv < Rin * Rin) continue;") && page.includes('k: "C:" + k, forest: 1, canopy: 1,'),
  "the page asks for the tiles in the band from the card trees' reach to CANOPY_RANGE (a forest job: never pruned with the chunks)");
ok(page.includes("m.opacityNode = TSL.step(canopyIn, TSL.positionWorld.sub(TSL.cameraPosition).length());") && page.includes("if (canopyIn) canopyIn.value = Rin;"),
  "…draws none inside the card trees' reach, which follows the preset");
ok(page.includes('if (k && k[0] === "C") return canopyDone(k.slice(2), m);') && page.includes("for (const f of canopy.values()) if (f.mesh) {") && page.includes('pt("canopy", updateCanopy);'),
  "…routes the results, places the meshes each frame, and refreshes the tiles four times a second");
ok(page.includes("if (f.mesh) { scene.remove(f.mesh); f.mesh.geometry.dispose(); canopyCells -= f.n; }"), "…and drops the tiles it leaves behind");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
