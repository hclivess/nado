/*
 * test_pieces_draw_as_their_skin_and_tile_their_texture_per_metre.mjs — how static/land-mesher.js draws built pieces
 * (land-world BOXES at 1 cm, any size), and what keeps it fast ("what about performance", operator 2026-11-06):
 *   1. a lone piece is its six faces (12 triangles), with uv in METRES (a 2 m side runs 0..2), so the material's texture
 *      repeats once per metre at any size; every vertex carries its material's atlas tile;
 *   2. flush opaque pieces hide the faces they press together: a 10 x 3 m wall of 300 flush planks is drawn as its skin,
 *      not 300 x 6 faces; glass never hides what is behind it and goes to the transparent part;
 *   3. a piece taller than a chunk is cut at the chunk line: each chunk draws its slice, the top face only in the top
 *      chunk, the bottom only in the bottom one, and no face at the cut;
 *   4. a far chunk (lod 2) skips pieces under LOD_SKIP_CM on every side and keeps the big ones;
 *   5. the measured worst case stays bounded: 20,000 scattered pieces mesh in the worker in a few hundred ms and draw at
 *      most 12 triangles each.
 *
 * Run: node tests/test_pieces_draw_as_their_skin_and_tile_their_texture_per_metre.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const q = Wd.plotCoords(Wd.firstWave()[44]), cu = q.u0 / 16, cv = q.v0 / 16;
const top = Wd.column(q.face, q.u0 + 8, q.v0 + 8).top, ch = Math.floor((top + 2) / 16) + 1;   // a chunk of open air
const y0 = ch * 1600;
const mesh = (boxes, lod = 0, c = ch) => M.meshChunk(q.face, cu, cv, c, null, boxes, lod);
const tris = (r, part = "pieces") => (r && r[part] ? r[part].idx.length / 3 : 0);

// 1. one piece
const r1 = mesh([[100, 100, y0 + 200, 200, 30, 50, Wd.B.planks]]);
ok(tris(r1) === 12, `a lone piece is six faces (${tris(r1)} triangles)`);
const uv = r1.pieces.uv, us = [], vs = [];
for (let i = 0; i < uv.length; i += 2) { us.push(uv[i]); vs.push(uv[i + 1]); }
ok(Math.abs(Math.max(...us, ...vs) - (y0 + 250) / 100) < 1e-4 && us.some((x) => Math.abs(x - 3) < 1e-6),
   "uv is in metres along each face (the texture repeats once per metre)");
ok([...r1.pieces.tile].every((t) => Wd.BLOCKS[Wd.B.planks].tex.includes(t)), "every vertex carries its material's atlas tile");

// 2. flush pieces draw their skin
const wall = [];
for (let i = 0; i < 50; i++) for (let j = 0; j < 6; j++) wall.push([200 + i * 20, 400, y0 + 300 + j * 50, 20, 5, 50, Wd.B.planks]);
const rw = mesh(wall);
ok(tris(rw) < 300 * 12 * 0.45, `300 flush planks draw ${tris(rw)} triangles, not ${300 * 12}: the faces pressed together are dropped`);
const glassWall = wall.map((b) => [b[0], b[1], b[2], b[3], b[4], b[5], Wd.B.glass]);
const rg = mesh(glassWall);
ok(tris(rg) === 0 && tris(rg, "glassy") === 300 * 12, "glass hides nothing and draws in the transparent part");

// 3. a tall piece across chunk lines
const tall = [[500, 500, y0 + 800, 40, 40, 3000, Wd.B.stonebrick]];        // 8 m into ch, through ch+1, into ch+2
const parts = [ch, ch + 1, ch + 2].map((c) => mesh(tall, 0, c));
ok(tris(parts[0]) === 10 && tris(parts[1]) === 8 && tris(parts[2]) === 10,
   `a 30 m pillar: its bottom chunk draws 5 faces, the middle 4, the top 5 (${parts.map((p) => tris(p)).join(", ")} triangles)`);

// 4. distance
const mix = [[10, 10, y0 + 100, 5, 5, 5, Wd.B.planks], [100, 100, y0 + 100, 15, 15, 15, Wd.B.planks], [300, 300, y0 + 100, 100, 100, 10, Wd.B.planks]];
ok(tris(mesh(mix, 0)) === 36 && tris(mesh(mix, 1)) === 36 && tris(mesh(mix, 2)) === 12, "a far chunk skips pieces under 20 cm on every side and keeps the slab");

// 5. the worst case
const scatter = [];
for (let y = 0; y < 16 && scatter.length < 20000; y++) for (let z = 0; z < 160 && scatter.length < 20000; z++)
  for (let x = 0; x < 160 && scatter.length < 20000; x += 4) scatter.push([x * 10, z * 10, y0 + y * 100 + (z % 2) * 10, 5, 5, 5, Wd.B.planks]);
const t0 = performance.now(), rs = mesh(scatter), ms = performance.now() - t0;
ok(tris(rs) <= 20000 * 12 && ms < 3000, `20,000 scattered pieces: ${tris(rs)} triangles in ${ms.toFixed(0)} ms (at most 12 each, bounded time)`);

// REAL MATERIALS ("A REAL HOUSE"): pieces come sorted by material, each one's run of triangles a draw group, so the page
// draws each in its scanned texture with its normal map (the 16 px atlas tile was the blocky look of every house)
{
  const mixed = mesh([[100, 100, y0 + 200, 100, 20, 50, Wd.B.brick], [300, 100, y0 + 200, 100, 20, 50, Wd.B.planks],
    [500, 100, y0 + 200, 100, 20, 50, Wd.B.brick], [700, 100, y0 + 200, 100, 200, 100, Wd.B.tiles, Wd.SLOPE_POS_Z]]);
  const G = mixed.pieces.groups || [];
  const covered = G.reduce((a, [, n]) => a + n, 0), ordered = G.every(([st, , m], i) => i === 0 || (st === G[i - 1][0] + G[i - 1][1] && m > G[i - 1][2]));
  ok(G.length === 3 && covered === mixed.pieces.idx.length && ordered && G.map((g) => g[2]).join() === [Wd.B.planks, Wd.B.brick, Wd.B.tiles].sort((a, b) => a - b).join(),
     `pieces come in one draw group per material, covering every triangle (${G.map((g) => Wd.BLOCKS[g[2]].key + ":" + g[1] / 3).join(", ")})`);
  const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), table = land.slice(land.indexOf("const PIECE_TEX = {"), land.indexOf("const pieceMats"));
  const building = ["planks", "darkwood", "brick", "plaster", "tiles", "cobble", "stonebrick", "door", "beam", "thatch"].map((k) => Wd.B[k]);
  ok(building.every((b) => new RegExp(`\\b${b}: \\["`).test(table)), "every building material has a real texture (planks, brick, plaster, tiles, stone, door, beam, thatch…)");
  ok(/m\.normalNode = TSL\.normalMap/.test(land) && /g\.addGroup\(start, count, mats\.length\)/.test(land), "with its normal map, one material per draw group");
}

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
