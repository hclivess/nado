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
const U = 54260, V = 80600, cu = Math.floor(U / Wd.CHUNK), cv = Math.floor(V / Wd.CHUNK), top = Wd.column(0, U, V).top, ch = Math.floor(top / Wd.CHUNK);
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
ok(page.includes("matGrass.colorNode = card.rgb.mul(TSL.instanceColor);"), "every grass clump is tinted by its instance colour (the painted blades in the clump's own tint)");
ok(page.includes("grass.setColorAt(gi++, c.setRGB(0.85 + 0.3 * t, 0.95 + 0.1 * t, 0.9 - 0.25 * t));"), "…green to yellow-green by the clump's own number");
ok(/const FLOWER_HEADS = \[\[0\.9, 0\.9, 0\.82\], \[0\.95, 0\.72, 0\.1\], \[0\.55, 0\.3, 0\.8\]/.test(page) && page.includes('TSL.mix(TSL.vec3(1), TSL.instanceColor, TSL.attribute("head", "float"))'), "a flower clump's heads take one of white, yellow, purple; its blades stay green");
ok(page.includes("clumpGeo = cardClump(0.7, 0.55); flowerGeo = bladeClump(4, true);") && page.includes("function grassCardTexture() {") && page.includes("alphaTest: 0.5 });") && page.includes("matGrass.opacityNode = card.a;"), "a grass clump is three crossed cards of a painted blade cluster, alpha-tested; a flower clump keeps its modelled blades and heads");
const cardIdx = page.slice(page.indexOf("function cardClump("), page.indexOf("function cardClump(") + 900);
ok(cardIdx.includes("for (let c = 0; c < 3; c++)") && cardIdx.includes("idx.push(base, base + 1, base + 2, base, base + 2, base + 3, base, base + 2, base + 1, base, base + 3, base + 2);"), "…twelve triangles a clump, each card indexed from both sides");
ok(page.includes("r = rnd() * 0.2, h = 0.2 + rnd() * 0.3, w = 0.012 + rnd() * 0.01, lean = 0.08 + rnd() * 0.14"), "the flower clump's blades spread to 0.2 m and lean 0.08–0.22 m");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
