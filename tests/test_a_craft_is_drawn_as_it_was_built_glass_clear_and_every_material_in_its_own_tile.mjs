/*
 * test_a_craft_is_drawn_as_it_was_built_glass_clear_and_every_material_in_its_own_tile.mjs — #188.
 * Found 2026-11-11 the moment the X-wing on plot 0·4999·3438 was boarded: photographed from the same camera before and
 * after, its clear canopy was a solid black wedge as a craft. A craft's pieces took their material from pieceMaterial
 * alone — glass got the atlas material, and a craft's geometry carried no atlas tile, so glass and every material
 * without a scanned texture (the colours, marble, the ores, a nav unit) sampled tile 0.
 *   1. a see-through block (glass, ice) of a craft is drawn in the glass material, every opaque one in its own;
 *   2. a box's corners carry its block's tiles as the chunk mesher lays them: top on top, bottom underneath, sides round;
 *   3. both geometries a craft is made of (a box, a part) carry the `tile` the atlas material reads, and both take
 *      their material from craftMaterial — nothing a craft draws asks pieceMaterial directly;
 *   4. glass is drawn after the opaque pieces (renderOrder 1), as the chunks draw it;
 *   5. every solid block the atlas material would draw has tiles to give.
 *
 * Run: node tests/test_a_craft_is_drawn_as_it_was_built_glass_clear_and_every_material_in_its_own_tile.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const src = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const B = Wd.B;

// the two decisions, lifted from the page's own source
const cut = (from, to) => { const a = src.indexOf(from), b = src.indexOf(to, a); if (a < 0 || b < 0) throw new Error("land.js lost " + from); return src.slice(a, b); };
const GLASS = { name: "the glass material" }, own = (blk) => ({ own: blk });
const { boxTiles, craftMaterial } = new Function("Wd", "pieceMaterial", "matGlassy",
  cut("const boxTiles =", "/** What a craft's piece") + cut("function craftMaterial(", "/** A box geometry") + "return { boxTiles, craftMaterial };")(Wd, own, GLASS);

// 1. the material
ok(craftMaterial(B.glass) === GLASS, "a craft's glass is drawn in the glass material");
ok(craftMaterial(B.ice) === GLASS, "…and its ice");
for (const k of ["steelplate", "planks", "thruster", "pilotseat", "navunit", "orange", "marble"])
  ok(craftMaterial(B[k]).own === B[k], `${k} is drawn in its own material`);
const see = Wd.BLOCKS.map((b, i) => [i, b]).filter(([, b]) => b && b.solid && b.see);
ok(see.length >= 2 && see.every(([i]) => craftMaterial(i) === GLASS), `every solid see-through block is glass on a craft (${see.map(([, b]) => b.key).join(", ")})`);

// 2. a box's tiles, in BoxGeometry's order of faces: +x -x +y -y +z -z, four corners each
const t = boxTiles([7, 8, 9]);
ok(t.length === 24, "a box has 24 corners, a tile each");
ok(t.slice(8, 12).every((x) => x === 7), "the top face (+y) carries the top's tile");
ok(t.slice(12, 16).every((x) => x === 9), "the underside (-y) the bottom's");
ok([...t.slice(0, 8), ...t.slice(16)].every((x) => x === 8), "the four sides the side's");
ok(boxTiles(Wd.BLOCKS[B.navunit].tex).every((x) => x === Wd.BLOCKS[B.navunit].tex[1]), "a nav unit's box is its own tile on every face, not tile 0");

// 3. both geometries carry the tile, and both ask craftMaterial
const boxFn = cut("function pieceBox(", "\n}\n"), craftFn = cut("function craftMesh(", "\n}\n"), partFn = cut("function partMeshes(", "\n}\n");
ok(/function pieceBox\(w, h, d, blk\)/.test(boxFn) && /setAttribute\("tile", [^;]*boxTiles\(Wd\.BLOCKS\[blk\]\.tex\)/.test(boxFn), "a craft's box carries its block's tiles");
ok(/setAttribute\("tile", [^;]*Wd\.BLOCKS\[blk\]\.tex\[1\]/.test(partFn), "a craft's part carries its material's side tile, as the mesher gives it docked");
ok(/pieceBox\([^;]*, b\[6\]\), craftMaterial\(b\[6\]\)/.test(craftFn), "a box of a craft is given its block and drawn by craftMaterial");
ok(/craftMaterial\(blk\)/.test(partFn) && /const blk = Wd\.toneBlock\(b, tone\)/.test(partFn), "a part's every tone is drawn by craftMaterial");
ok(!/\bpieceMaterial\(/.test(craftFn) && !/\bpieceMaterial\(/.test(partFn), "nothing a craft draws asks pieceMaterial directly");
ok((src.match(/\bpieceBox\(/g) || []).length === 2, "pieceBox is called from one place (a caller without a block would draw tile 0 again)");

// 4. glass after the opaque pieces
ok(/if \(m\.material === matGlassy\) m\.renderOrder = 1;/.test(craftFn), "a craft's glass is drawn after what is seen through it");
ok(/new THREE\.Mesh\(geom\(m\.glassy\), matGlassy\); me\.renderOrder = 1/.test(src), "…as the chunks draw a docked pane");

// 5. every block the atlas material would draw has three tiles
const bad = Wd.BLOCKS.map((b, i) => [i, b]).filter(([, b]) => b && b.solid && !(Array.isArray(b.tex) && b.tex.length === 3 && b.tex.every(Number.isInteger)));
ok(bad.length === 0, "every solid block has a top, a side and a bottom tile" + (bad.length ? ": " + bad.map(([i, b]) => i + ":" + b.key).join(" ") : ""));

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
