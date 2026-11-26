/*
 * test_the_meadow_is_a_blanket_of_tinted_grass_with_white_yellow_and_purple_flowers.mjs — #183 step 3 (the operator's
 * concept picture: a dense meadow in many greens with white, yellow and purple flowers; the live meadow beside it,
 * 2026-11-11: stiff bright spikes over bare ground, a few yellow heads). The mesher's scatter, run in node on a chunk
 * of meadow, and the page's clump as source:
 *   1. one clump in about twelve is a flower clump (was one in 25) — measured over a chunk's grass, not read off a constant;
 *   2. the clumps are painted CARDS (step 3b): three crossed quads, twelve triangles a clump against the fifty-four of
 *      the modelled blades, so the mesher scatters about ten a square metre at a third of the triangles;
 *   3. the page tints every grass clump by its own number (an instance colour, green to yellow-green, never grey) and
 *      gives a flower clump heads in one of three colours — white, yellow, purple — on a head attribute, the blades green;
 *   4. the clumps spread wider and lean more than before, so the blanket closes.
 * Run: node tests/test_the_meadow_is_a_blanket_of_tinted_grass_with_white_yellow_and_purple_flowers.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const M = await import(join(ROOT, "static", "land-mesher.js")), Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// a chunk of the #183 meadow (plot 0·5037·3391's column), meshed with its grass at the near level of detail
// (moved 1.4 km east 2026-11-22: with continents the #183 meadow became a wooded hill; this meadow lies 39 m over the sea)
const U = 55660, V = 80600, cu = Math.floor(U / Wd.CHUNK), cv = Math.floor(V / Wd.CHUNK), top = Wd.column(0, U, V).top, ch = Math.floor(top / Wd.CHUNK);
let flowers = 0, clumps = 0, chunks = 0;
for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
  const r = M.meshChunk(0, cu + dx, cv + dy, ch, null, null, 0, true);
  if (!r.grass) continue;
  chunks++; clumps += r.grass.kind.length; for (const k of r.grass.kind) flowers += k;
}
ok(chunks > 5 && clumps > 2000, `${chunks} chunks of meadow hold ${clumps} grass clumps`);
const share = flowers / clumps;
ok(share > 1 / 16 && share < 1 / 9, `one clump in ${(1 / share).toFixed(1)} is a flower clump (about one in twelve)`);
const perM2 = clumps / (chunks * Wd.CHUNK * Wd.CHUNK);
ok(perM2 > 7 && perM2 < 12, `about ${perM2.toFixed(1)} clumps a square metre (GRASS_DENSITY 10 on the grassy share of the ground)`);
ok(perM2 * 12 < 6 * 54, `…at ${Math.round(perM2 * 12)} triangles a square metre, under the modelled blades' ${6 * 54}`);

const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(page.includes("matGrass.colorNode = shadeByClouds(card.rgb.mul(TSL.instanceColor));"), "every grass clump is tinted by its instance colour (the painted blades in the clump's own tint), under the cloud shadow (#183 step 4)");
// the tints and the painted blades as measured against the Chlorophyll reference (2026-11-21: its near grass rgb 50, 62, 20 —
// red ~0.8 of the green, blue a third; ours read lime-yellow at blue a sixth): read from the source, not pinned to digits
const tint = page.match(/tan \? c\.setRGB\(1\.05, 0\.92, 0\.55\) : c\.setRGB\(([\d.]+) \+ ([\d.]+) \* t, ([\d.]+) \+ ([\d.]+) \* t, ([\d.]+) - ([\d.]+) \* t\)/);
const tb = tint ? [0, 1].map((t) => [Number(tint[1]) + Number(tint[2]) * t, Number(tint[3]) + Number(tint[4]) * t, Number(tint[5]) - Number(tint[6]) * t]) : null;
ok(tb && page.includes("tan = ((r * 613) % 1) < 0.17") && tb.every(([r, g, b]) => b >= 0.75 && r / g > 0.85 && r / g < 1.2) && tb[0].join() !== tb[1].join(),
  "…tinted by the clump's own number from one green to another (blue never under 0.75: no yellow cast), one in six the tan of grass gone to seed: " + JSON.stringify(tb));
const paint = page.match(/g\.fillStyle = `rgb\(\$\{Math\.round\(255 \* L(?: \* ([\d.]+))?\)\}, \$\{Math\.round\(255 \* L\)\}, \$\{Math\.round\(255 \* L \* ([\d.]+)\)\}\)`/);
const red = paint ? Number(paint[1] || 1) : NaN, blue = paint ? Number(paint[2]) : NaN;   // (no factor: red level with the green)
ok(paint && red >= 0.78 && red <= 1.0 && blue >= 0.3 && blue <= 0.4,   // (a third, the reference's ratio: 0.45 had been set against the bloom's veil)
   `the painted blades are the reference's olive: red ${red} and blue ${blue} of the green`);
// the blades' lightness, root to tip. 2026-11-22 set it against the reference's sunlit MIDDLE meadow (86, 100, 38): tips
// of 0.43 read (48, 70, 23), 0.56 overshot yellow (92, 107, 37). 2026-11-24 measured like for like, the reference's
// FOREGROUND grass (56, 68, 23), and in one picture — a ratio that holds whatever the sun's height — its grass underfoot is
// 0.56 as light as its middle meadow, ours 0.81 at a tip of 0.49; at 0.40 (with the ground under the blades shaded) 0.62,
// the near grass (59, 76, 24)
{ const lm = page.match(/const L = ([\d.]+) \+ ([\d.]+) \* t1 \*\* 0\.8;/), root = lm && Number(lm[1]), tip = lm && Number(lm[1]) + Number(lm[2]);
  ok(lm && root >= 0.08 && root <= 0.12 && tip >= 0.36 && tip <= 0.45, `the blades run from ${root} at the root to ${tip && tip.toFixed(2)} at the tip — the reference's foreground grass, dark to the ground (0.49 read 0.81 of the middle meadow against its 0.56)`); }
ok(page.includes("h = 0.58 + rnd() * 0.22, s = 0.05") && page.includes("h = (flower ? 0.4 : 0.2) + rnd() * 0.3"), "a flower clump's heads stand over the cards' tops on taller stems");
ok(/const FLOWER_HEADS = \[\[0\.9, 0\.9, 0\.82\], \[0\.95, 0\.72, 0\.1\], \[0\.55, 0\.3, 0\.8\]/.test(page) && page.includes('TSL.mix(TSL.vec3(1), TSL.instanceColor, TSL.attribute("head", "float"))'), "a flower clump's heads take one of white, yellow, purple; its blades stay green");
ok(page.includes("clumpGeo = cardClump(0.7, 0.55); flowerGeo = bladeClump(4, true);") && page.includes("function grassCardTexture() {") && page.includes("alphaTest: 0.5 });") && page.includes("matGrass.opacityNode = card.a;"), "a grass clump is three crossed cards of a painted blade cluster, alpha-tested; a flower clump keeps its modelled blades and heads");
const cardIdx = page.slice(page.indexOf("function cardClump("), page.indexOf("function cardClump(") + 900);
ok(cardIdx.includes("for (let c = 0; c < 3; c++)") && cardIdx.includes("idx.push(base, base + 1, base + 2, base, base + 2, base + 3, base, base + 2, base + 1, base, base + 3, base + 2);"), "…twelve triangles a clump, each card indexed from both sides");
ok(page.includes("r = rnd() * 0.2, h = (flower ? 0.4 : 0.2) + rnd() * 0.3, w = 0.012 + rnd() * 0.01, lean = 0.08 + rnd() * 0.14"), "the flower clump's blades spread to 0.2 m and lean 0.08–0.22 m");
// GRASS FURTHER OUT (2026-11-25, operator: "Grass"): past lod 1 (~56 m) the meadow was the ground texture alone — the blades now
// reach FAR_GRASS chunks (~100 m) at an eighth of their density, desktop only (view 6+), and the mesher takes the density as asked
{
  const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
  const fg = /const FAR_GRASS = (\d+);/.exec(land);
  ok(fg && +fg[1] >= 5 && +fg[1] <= 8 && land.includes("const grassDensity = (lod, dist) => (!SET.grass ? 0 : lod === 0 ? 1 : lod === 1 ? 1 / 3 : !PHONE && SET.view >= 6 && dist <= FAR_GRASS ? 1 / 8 : 0);")
    && land.includes("lod: c.lod, grass: c.gd });") && land.includes("c.gd !== grassDensity(lodNow, dd)"),
    `the blades reach ${fg ? fg[1] : "?"} chunks out at an eighth of their density on a desktop, and follow the player across that band`);
  ok(mesher.includes('const gd = typeof grassOn === "number" ? grassOn : grassOn ? (lod === 0 ? 1 : lod === 1 ? 1 / 3 : 0) : 0;')
    && mesher.includes("scatterGrass(smooth, GRASS_DENSITY * gd, under)"), "the mesher scatters at the density the page asks for (true/false still meaning what it did)");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
