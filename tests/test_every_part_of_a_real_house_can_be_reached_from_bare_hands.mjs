/*
 * test_every_part_of_a_real_house_can_be_reached_from_bare_hands.mjs — static/land-recipes.json ("continue working until
 * the crafting tree has all components to build A REAL HOUSE with all the proper ways to get there", operator 2026-11-06).
 * A player starts with nothing; this follows the rules the way they would:
 *   1. what bare hands gather from the planet (breaking yields with no tool needed), then every recipe whose ingredients,
 *      stations and tools (any tool of a class counts, as the world server judges) they can reach, then what those new
 *      tools let them break — until nothing new can be reached;
 *   2. every part of a house is reachable that way: a foundation (stone brick laid in mortar, cobblestone), walls (planks,
 *      timber beams, fired brick, plaster), a floor, a roof (roof tiles or thatch), windows (glass), a door (with its
 *      hinges and nails), and the iron to make them; and each is something a player can place, where it is a material;
 *   3. the rules hold together: every ingredient and product is an item, tool or station; every "with" names a station,
 *      a tool or a tool class; every placeable item places a real block; every block a piece can be made of has a tile.
 *
 * Run: node tests/test_every_part_of_a_real_house_can_be_reached_from_bare_hands.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 3. coherence
const known = (id) => id in R.items || id in R.tools || id in R.stations;
const bad = R.recipes.flatMap((r) => [...r.makes, ...r.uses].map(([id]) => id).filter((id) => !known(id)).map((id) => `${r.id}:${id}`));
ok(!bad.length, `every ingredient and product is an item, tool or station (${bad.join(", ") || "all"})`);
const classes = new Set(Object.values(R.tools).map((t) => t.class));
const badWith = R.recipes.flatMap((r) => (r.with || []).filter((w) => !(w in R.stations || w in R.tools || classes.has(w))).map((w) => `${r.id}:${w}`));
ok(!badWith.length, `every "with" is a station, a tool or a tool class (${badWith.join(", ") || "all"})`);
const badPlace = Object.entries(R.items).filter(([, it]) => "places" in it && !(it.places > 0 && it.places < Wd.BLOCKS.length)).map(([k]) => k);
ok(!badPlace.length, `every placeable item places a real block (${badPlace.join(", ") || "all"})`);
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), paint = land.slice(land.indexOf("const PAINT = {"), land.indexOf("function paintAtlas"));
const noTile = Object.values(R.items).filter((it) => it.places).map((it) => Wd.BLOCKS[it.places].tex[1]).filter((t) => !new RegExp(`\\b${t}: \\[`).test(paint));
ok(!noTile.length && Wd.ATLAS_TILES > Math.max(...Wd.BLOCKS.filter((b) => b.tex).flatMap((b) => b.tex)), `every placeable block has its atlas tile (${noTile.join(", ") || "all"})`);

// 1. reach, the way a player would
const have = new Set(), tools = new Set(), stations = new Set();
const hasClass = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
let grew = true, rounds = 0;
while (grew && rounds++ < 50) {
  grew = false;
  for (const [, rule] of Object.entries(R.breaking)) {
    if (typeof rule !== "object" || !rule.yields) continue;
    if (rule.needs && !hasClass(rule.needs)) continue;
    for (const [id] of rule.yields) if (!have.has(id)) { have.add(id); grew = true; }
    if (rule.bonus && !have.has(rule.bonus[0])) { have.add(rule.bonus[0]); grew = true; }
  }
  for (const r of R.recipes) {
    if (!r.uses.every(([id]) => have.has(id)) || !(r.with || []).every((w) => stations.has(w) || hasClass(w))) continue;
    for (const [id] of r.makes) {
      const set = id in R.tools ? tools : id in R.stations ? stations : have;
      if (!set.has(id)) { set.add(id); grew = true; }
    }
  }
}
// the planet's breaking table must cover what lies in the wild (the blocks a player meets): grass, earth, leaves, litter
ok(["dirt", "fiber", "sticks", "stone"].every((i) => have.has(i)), "bare hands gather earth, fibre, sticks and stone");

// 2. a house
const HOUSE = {
  "foundation: stone brick laid in mortar": ["stonebrick", "mortar", "cobble"],
  "walls: planks, timber beams, fired brick, plaster": ["planks", "beam", "brick", "plaster"],
  "roof: roof tiles or thatch": ["tiles", "thatch"],
  "windows: framed, glazed": ["glass", "window"],
  "a door, with its hinges and nails": ["door", "hinges", "nails"],
  "iron for the ironwork": ["iron"],
};
for (const [what, ids] of Object.entries(HOUSE)) ok(ids.every((i) => have.has(i)), `${what} — reachable from bare hands (${ids.filter((i) => !have.has(i)).join(", ") || "all"})`);
for (const id of ["stonebrick", "cobble", "planks", "beam", "brick", "plaster", "tiles", "thatch", "glass", "door", "window"])
  ok(!!R.items[id].places, `${id} is something a player can build with`);
ok(["axe", "pick", "shovel", "hammer", "iron_axe", "iron_pick"].every((t) => tools.has(t)) && ["campfire", "workbench", "kiln", "bloomery", "anvil"].every((s) => stations.has(s)),
   "and every tool and station on the way is reachable too");
ok(R.items.door.unit && R.items.door.unit.length === 3, "a door is a unit: made whole, placed at its size");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
