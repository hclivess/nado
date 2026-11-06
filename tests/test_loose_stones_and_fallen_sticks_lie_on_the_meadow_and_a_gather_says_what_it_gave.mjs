/*
 * test_loose_stones_and_fallen_sticks_lie_on_the_meadow_and_a_gather_says_what_it_gave.mjs — the way into the tool web
 * must be findable ("where the fuck do i take stone and sticks?", "it gives, but it is only visible in the bag!!!",
 * operator 2026-11-06):
 *   1. loose stones and fallen sticks lie on the landing meadow, in plain sight: dozens in a 3 x 3 block of plots, each
 *      in the air cell just above the ground, and only on land;
 *   2. they come up BY HAND, quickly (no tool, a fraction of a second): a stone gives stone, a stick gives sticks — the
 *      rules the page and the world server share (static/land-recipes.json);
 *   3. they are walked through (not solid) and drawn as what they are — a rock in the ground's material (all rock, no
 *      grass growing on it) and a branch in bark — never as a cube;
 *   4. every gather says what it gave: the page shows the inventory's gains beside the crosshair, and the first inventory
 *      after (re)connecting is not announced as a pickup.
 * (tests/test_land_players_gather_make_tools_craft_and_trade.py picks both up through the real world server.)
 *
 * Run: node tests/test_loose_stones_and_fallen_sticks_lie_on_the_meadow_and_a_gather_says_what_it_gave.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
const q = Wd.plotCoords(Wd.firstWave()[44]);
let pebbles = 0, twigs = 0, misplaced = 0, litterChunk = null;
for (let u = q.u0; u < q.u0 + 48; u++) for (let v = q.v0; v < q.v0 + 48; v++) {
  const c = Wd.column(q.face, u, v);
  for (let h = c.top - 1; h <= c.top + 3; h++) {
    const b = Wd.terrainBlock(q.face, u, v, h);
    if (!Wd.LITTER.has(b)) continue;
    if (h !== c.top + 1 || c.top <= Wd.SEA) misplaced++;
    if (b === Wd.B.pebble) pebbles++; else twigs++;
    if (!litterChunk) litterChunk = { cu: Math.floor(u / 16), cv: Math.floor(v / 16), ch: Math.floor(h / 16) };
  }
}
ok(pebbles >= 40 && twigs >= 30, `stones and sticks lie on the meadow (${pebbles} stones, ${twigs} sticks in 48 x 48 m)`);
ok(misplaced === 0, "each lies in the air cell just above the ground, on land");

// 2
const rp = RULES.breaking[String(Wd.B.pebble)], rt = RULES.breaking[String(Wd.B.twigs)];
ok(rp && !rp.needs && rp.hard <= 0.25 && rp.yields.some(([i]) => i === "stone"), "a loose stone comes up by hand in a moment and gives stone");
ok(rt && !rt.needs && rt.hard <= 0.25 && rt.yields.some(([i]) => i === "sticks"), "a fallen stick comes up by hand in a moment and gives sticks");
const axe = RULES.recipes.find((r) => r.makes[0][0] === "axe"), cord = RULES.recipes.find((r) => r.makes[0][0] === "cordage");
ok(axe.uses.every(([i]) => ["sticks", "stone", "cordage"].includes(i)) && cord.uses.every(([i]) => i === "fiber"),
   "so a stone axe needs only what lies on the ground and grows on it (sticks, stone, fiber for cordage)");

// 3
ok(!Wd.BLOCKS[Wd.B.pebble].solid && !Wd.BLOCKS[Wd.B.twigs].solid, "both are walked through");
const r = M.meshChunk(q.face, litterChunk.cu, litterChunk.cv, litterChunk.ch, null, null, 0);
ok(r.stones && r.stones.w1.length && Array.from(r.stones.w1).every((w, i) => (i % 4 === 2 ? w === 1 : w === 0)),
   "a stone is drawn in the ground's material, all rock");
ok(!r.solid, "no litter is drawn as a cube");
ok(r.bark && Array.from(r.bark.wind).some((w, i) => i % 4 !== 3 && w === 0), "a fallen stick is drawn in bark, lying still");

// 4
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const invHandler = land.slice(land.indexOf('m.t === "inv"'), land.indexOf('m.t === "offers"'));
ok(/if \(invSeen\) pickup\(inv\.items, m\.items/.test(invHandler) && invHandler.indexOf("pickup(") < invHandler.indexOf("inv.items = m.items"),
   "every inventory update announces its gains (compared before the bag is replaced)");
const hello = land.slice(land.indexOf('m.t === "hello"'), land.indexOf('m.t === "plot"'));
ok(/invSeen = false/.test(hello), "a (re)connect's inventory is not announced as a pickup");
ok(/id="pickup"/.test(html) && /#pickup\{/.test(html), "the page has the place beside the crosshair to say it");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
