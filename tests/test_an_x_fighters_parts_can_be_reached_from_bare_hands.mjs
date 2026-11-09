/*
 * test_an_x_fighters_parts_can_be_reached_from_bare_hands.mjs — static/land-recipes.json (#146: "tech up and build an X
 * fighter … you are not adding any materials — you only add the initial (like iron ore) and then you add techs all the
 * way until you can build an X fighter", operator 2026-11-09; the chain is doc/land-tech-to-flight.md).
 * A player starts with nothing; this follows the rules the way they would (as the house test does):
 *   1. bare hands gather from the planet, recipes whose ingredients, stations and tools are reached make more, new tools
 *      break more — until nothing new is reached;
 *   2. the X fighter's parts are reached that way: steel plate for the hull, a thruster, a pilot seat — and every step on
 *      the way (steel, copper, wire, gears, silicon, circuits, power cells, motors; the blast furnace, the machine shop);
 *   3. nothing is conjured: every raw input of the chain is something the planet's breaking table yields (an ore, coal,
 *      sand, clay…), and each new item comes only from a recipe;
 *   4. the hull, the thruster and the seat are things a player places — the thruster and the seat as whole units — each
 *      a real block with its own atlas tile, a name in 17 languages, and broken back into its item with a pick.
 *
 * Run: node tests/test_an_x_fighters_parts_can_be_reached_from_bare_hands.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const L10N = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. reach
const have = new Set(), tools = new Set(), stations = new Set(), byHand = new Set();
const hasClass = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
let grew = true, rounds = 0;
while (grew && rounds++ < 60) {
  grew = false;
  for (const [, rule] of Object.entries(R.breaking)) {
    if (typeof rule !== "object" || !rule.yields) continue;
    if (rule.needs && !hasClass(rule.needs)) continue;
    for (const [id] of rule.yields) { byHand.add(id); if (!have.has(id)) { have.add(id); grew = true; } }
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

// 2. the parts and the way there
const CHAIN = ["steel", "copper", "wire", "steel_plate", "gear", "silicon", "circuit", "power_cell", "motor", "thruster", "pilot_seat"];
ok(CHAIN.every((i) => have.has(i)), `every step of the chain is reached from bare hands (${CHAIN.filter((i) => !have.has(i)).join(", ") || "all"})`);
ok(["blast_furnace", "machine_shop"].every((s) => stations.has(s)), "…and its two new stations, the blast furnace and the machine shop");
ok(["steel_plate", "thruster", "pilot_seat"].every((i) => have.has(i)), "an X fighter's parts — hull plate, thruster, pilot seat — are reached");

// 3. nothing conjured: the chain's raw inputs all come out of the ground, and every chain item is a recipe's product
const made = new Set(R.recipes.flatMap((r) => r.makes.map(([id]) => id)));
const raw = new Set();
const walk = (id, seen = new Set()) => {
  if (seen.has(id)) return; seen.add(id);
  const r = R.recipes.find((x) => x.makes.some(([m]) => m === id));
  if (!r) { raw.add(id); return; }
  for (const [u] of r.uses) walk(u, seen);
  for (const w of r.with || []) if (w in R.stations) walk(w, seen);
};
for (const id of ["thruster", "pilot_seat", "steel_plate"]) walk(id);
const notGround = [...raw].filter((id) => !byHand.has(id));
ok(!notGround.length, `every raw input of the chain is gathered from the planet: ${[...raw].sort().join(", ")}${notGround.length ? " — NOT gathered: " + notGround.join(", ") : ""}`);
ok(CHAIN.every((i) => made.has(i)), "each chain item comes from a recipe");

// 4. placed things: real blocks, tiles, names, broken back
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), paint = land.slice(land.indexOf("const PAINT = {"), land.indexOf("function paintAtlas"));
for (const [id, key] of [["steel_plate", "steelplate"], ["thruster", "thruster"], ["pilot_seat", "pilotseat"]]) {
  const blk = R.items[id].places;
  ok(blk === Wd.B[key] && blk < Wd.BLOCKS.length, `${id} places the ${key} block (${blk})`);
  const tile = Wd.BLOCKS[blk].tex[1];
  ok(tile < Wd.ATLAS_TILES && new RegExp(`\\b${tile}: \\[`).test(paint), `…drawn with its own atlas tile (${tile})`);
  const br = R.breaking[String(blk)];
  ok(br && br.class === "pick" && br.yields[0][0] === id, `…and a pick takes it down back into a ${id}`);
}
ok(R.items.thruster.unit && R.items.pilot_seat.unit && !R.items.steel_plate.unit, "the thruster and the seat are whole units; steel plate is cut to any size");
const keys = CHAIN.map((i) => "land.i." + i).concat(["land.s.blast_furnace", "land.s.machine_shop"]);
const langs = Object.keys(L10N);
ok(langs.length === 17 && langs.every((l) => keys.every((k) => L10N[l][k])), `every new item and station is named in all 17 languages (${langs.length})`);
ok(/64: \["steel", 1, 0\.38\]/.test(land) && /if \(name === "steel"\) m\.metalness = 0\.55;/.test(land), "built steel is drawn as metal");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
