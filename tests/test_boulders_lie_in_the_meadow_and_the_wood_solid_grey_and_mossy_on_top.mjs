/*
 * test_boulders_lie_in_the_meadow_and_the_wood_solid_grey_and_mossy_on_top.mjs — #183 step 5 (the concept picture's mossy
 * boulder; #181 "stones read as brown potatoes"). From the photographs (land research look/step5/OBSERVED.md: the Tahoe
 * erratic): a boulder is the planet's own rock a metre and a half across, pale grey, rounded but for one flat split face,
 * sitting on the ground, moss in yellow-green patches on its upper faces and none on its sides. land-world.js places one
 * (litterAt: BOULDER_MEADOW / BOULDER_WOOD columns per boulder, a density chosen for the look), land-mesher.js draws it,
 * and it is SOLID to the player and to a craft (the cell), broken only with a pick. This pins:
 *   1. the block: solid, litter (drawn as a rock, never a cube), never swept by a placed block, never burnt, not ground;
 *   2. the planet: over a meadow the boulders come about one per BOULDER_MEADOW columns, over a wood one per
 *      BOULDER_WOOD, none on a column at or under the sea, none in a desert;
 *   3. the mesh: a chunk holding a boulder draws it in the stones buffer, 0.9–1.6 m across, its faces pale grey, moss only
 *      on faces whose normal points up, a flat face on one side (several vertices on one plane), at every detail level;
 *   4. the rule: breaking a boulder needs a pick and yields cobble and stone.
 * Run: node tests/test_boulders_lie_in_the_meadow_and_the_wood_solid_grey_and_mossy_on_top.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js")), M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const B = Wd.B, b = B.boulder;
// 1. the block
ok(Number.isInteger(b) && Wd.BLOCKS[b].solid === true && Wd.LITTER.has(b) && !Wd.SWEPT.has(b) && !Wd.BURNS.has(b) && !Wd.NATURAL.has(b), `the boulder (block ${b}) is solid, litter-drawn, never swept, never burnt, not ground`);
// 2. the planet: count the litter over regions of one biome
const count = (biome, u0, v0, size) => { let n = 0, cols = 0, other = 0; for (let v = v0; v < v0 + size; v++) for (let u = u0; u < u0 + size; u++) { const c = Wd.column(0, u, v); if (c.biome !== biome || c.top <= Wd.SEA) { other++; continue; } cols++; if (Wd.litterAt(0, u, v, c) === b) n++; } return { n, cols, other }; };
let meadow = null, wood = null, desert = null;
for (let v = 79000; v < 82000 && !(meadow && wood && desert); v += 200) for (let u = 53000; u < 56500 && !(meadow && wood && desert); u += 200) {
  const c = Wd.column(0, u, v);
  if (c.top <= Wd.SEA) continue;
  if (c.biome === "grass" && !meadow) { const r = count("grass", u, v, 200); if (r.cols > 25000) meadow = r; }
  if (c.biome === "forest" && !wood) { const r = count("forest", u, v, 200); if (r.cols > 15000) wood = r; }
  if (c.biome === "desert" && !desert) { const r = count("desert", u, v, 200); if (r.cols > 10000) desert = r; }
}
ok(meadow && wood, `a meadow and a wood of some size are found to count over (${meadow && meadow.cols} and ${wood && wood.cols} columns)`);
const expectM = meadow.cols / Wd.BOULDER_MEADOW, expectW = wood.cols / Wd.BOULDER_WOOD;
ok(meadow.n > expectM * 0.4 && meadow.n < expectM * 2.2, `over the meadow the boulders come about one per ${Wd.BOULDER_MEADOW} columns (${meadow.n} over ${meadow.cols}: expected ~${expectM.toFixed(1)})`);
ok(wood.n > expectW * 0.4 && wood.n < expectW * 2.2, `over the wood one per ${Wd.BOULDER_WOOD} (${wood.n} over ${wood.cols}: expected ~${expectW.toFixed(1)})`);
if (desert) ok(desert.n === 0, `none in the desert (${desert.cols} columns)`); else console.log("     (no desert within the sampled square: its check is skipped)");
{ let sea = 0; for (let v = 79000; v < 82000; v += 7) for (let u = 53000; u < 56500; u += 7) { const c = Wd.column(0, u, v); if (c.top <= Wd.SEA && Wd.litterAt(0, u, v, c) === b) sea++; } ok(sea === 0, "none on a column at or under the sea"); }
// 3. the mesh: the first boulder in the meadow, its chunk meshed at every detail level
let at = null;
for (let v = 79000; v < 82000 && !at; v++) for (let u = 53000; u < 56500 && !at; u++) { const c = Wd.column(0, u, v); if (c.biome === "grass" && c.top > Wd.SEA && Wd.litterAt(0, u, v, c) === b) at = { u, v, c }; }
ok(!!at, `a boulder is found at (${at && at.u}, ${at && at.v})`);
for (const lod of [0, 1, 2]) {
  const cu = Math.floor(at.u / Wd.CHUNK), cv = Math.floor(at.v / Wd.CHUNK), ch = Math.floor((at.c.top + 1) / Wd.CHUNK);
  const m = M.meshChunk(0, cu, cv, ch, new Map(), [], lod, false), st = m && m.stones;
  if (!st || !st.pos || !st.pos.length) { ok(false, `lod ${lod}: the chunk's stones buffer holds the boulder`); continue; }
  // the boulder's triangles: those within 1.5 m of its column's centre (a pebble is 0.2 m and lies off-centre)
  const anchor = m.anchor, fr = Wd.frameOf(0, at.u + 0.5, at.v + 0.5), centre = Wd.posOf(0, at.u + 0.5, at.v + 0.5, at.c.height);
  const pos = st.pos, nor = st.nor, col = st.col, n = pos.length / 3;
  const local = (i) => { const p = [pos[i * 3] + anchor[0] - centre[0], pos[i * 3 + 1] + anchor[1] - centre[1], pos[i * 3 + 2] + anchor[2] - centre[2]]; return [p[0] * fr.east[0] + p[1] * fr.east[1] + p[2] * fr.east[2], p[0] * fr.north[0] + p[1] * fr.north[1] + p[2] * fr.north[2], p[0] * fr.up[0] + p[1] * fr.up[1] + p[2] * fr.up[2]]; };
  const mine = []; for (let i = 0; i < n; i++) { const l = local(i); if (Math.hypot(l[0], l[1]) < 1.5 && Math.abs(l[2]) < 2) mine.push([i, l]); }
  const xs = mine.map(([, l]) => l[0]), ys = mine.map(([, l]) => l[1]), zs = mine.map(([, l]) => l[2]);
  const wide = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)), tall = Math.max(...zs) - Math.min(...zs);
  ok(mine.length >= 60 && wide >= 0.9 && wide <= 1.7 && tall >= 0.5, `lod ${lod}: the boulder is drawn ${wide.toFixed(2)} m across and ${tall.toFixed(2)} m high from ${mine.length} vertices`);
  let upMoss = 0, upAll = 0, sideMoss = 0, sideAll = 0, pale = 0;
  for (const [i] of mine) {
    const nz = nor[i * 3] * fr.up[0] + nor[i * 3 + 1] * fr.up[1] + nor[i * 3 + 2] * fr.up[2], r = col[i * 3], g = col[i * 3 + 1], bl = col[i * 3 + 2];
    const moss = g > r * 1.1 && g > bl * 1.6;
    if (nz > 0.5) { upAll++; if (moss) upMoss++; } else { sideAll++; if (moss) sideMoss++; }
    if (!moss && r > 0.5 && Math.abs(r - bl) < 0.08) pale++;
  }
  ok(upAll > 0 && upMoss / upAll > 0.3 && upMoss / upAll < 0.85, `…moss in patches on its upper faces (${upMoss} of ${upAll} upward vertices)`);
  ok(sideAll > 0 && sideMoss === 0, `…and none on its sides (${sideAll} side vertices)`);
  ok(pale > mine.length / 3, `…the rest pale grey, not the pebble's cool blue-grey (${pale} vertices)`);
  // the split face: along the rock's own x (turned by its rotation) a share of the vertices lie on one plane — found as the
  // most common projection on any of 36 directions, to the centimetre
  let best = 0;
  for (let k = 0; k < 36; k++) { const a = k * Math.PI / 36, bins = new Map(); for (const [, l] of mine) { const p = Math.round((l[0] * Math.cos(a) + l[1] * Math.sin(a)) * 100); bins.set(p, (bins.get(p) || 0) + 1); } best = Math.max(best, ...bins.values()); }
  ok(best >= mine.length * 0.12, `…and a flat split face: ${best} of ${mine.length} vertices on one plane`);
}
// 4. the rule
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8")).breaking[String(b)];
ok(R && R.needs === "pick" && R.class === "pick" && R.yields.some(([k]) => k === "cobble") && R.bonus && R.bonus[0] === "stone" && R.hard >= 3, `breaking a boulder needs a pick and yields cobble and stone (${JSON.stringify(R)})`);
ok(/N_BLOCKS = 86/.test(readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8")) && Wd.BLOCKS.length === 86, "the world server counts the block");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
