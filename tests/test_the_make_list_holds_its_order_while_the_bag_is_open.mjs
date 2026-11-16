/*
 * test_the_make_list_holds_its_order_while_the_bag_is_open.mjs — playtest 2026-11-16, the agent's phone page: the Bag's
 * Make list puts what can be made now first and was sorted afresh on every redraw — and a make redraws it. A recipe that
 * ran out of its makings dropped from the top group and the row below slid under the finger: making cordage until the
 * fibre ran out, the next tap on the same spot made planks of the player's wood. land.js renderBag keeps the order
 * (makeOrder) while the Bag stays open; opening it or changing the tab sorts again. The page's own ordering runs here.
 * Run: node tests/test_the_make_list_holds_its_order_while_the_bag_is_open.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf("  if (!makeOrder) makeOrder = "), b = page.indexOf("\n", page.indexOf("  const recipes = makeOrder.map("));
ok(a > 0 && b > a, "(the Make list's ordering, from renderBag)");
const order = new Function("RULES", "inv", "canMake", "state", "let makeOrder = state.order;\n" + page.slice(a, b) + "\nstate.order = makeOrder;\nreturn recipes.map((r) => r.id);");
// the book's own needs, against a bag: a recipe can be made when the bag holds what it uses (stations and tools waved through)
const bag = { fiber: 3, wood: 5 };
const inv = { items: bag, tools: [], stations: [] };
const canMake = (r) => r.uses.every(([id, n]) => (bag[id] || 0) >= n);
const state = { order: null };
const first = order(RULES, inv, canMake, state);
const iC = first.indexOf("cordage"), iP = first.indexOf("planks");
ok(iC >= 0 && iP >= 0 && iC < 5 && iP < 5, `opened with 3 fibre and 5 wood: cordage and planks near the top (${iC}, ${iP})`);
bag.fiber = 0;                                            // cordage made: the fibre is gone — the Bag redraws
const after = order(RULES, inv, canMake, state);
ok(JSON.stringify(after) === JSON.stringify(first), "after the make, every row stays where it was (the finger's next tap hits the same recipe)");
ok(after.indexOf("cordage") === iC && !canMake(RULES.recipes.find((r) => r.id === "cordage")), "…cordage, no longer makeable, keeps its row (its button disabled)");
state.order = null;                                       // the Bag closed and opened again, or the tab changed
const reopened = order(RULES, inv, canMake, state);
ok(reopened.indexOf("cordage") > reopened.indexOf("planks"), "opened again: sorted afresh — what can be made now first, cordage below planks");
ok(/function palette\(open\) \{[\s\S]*?makeOrder = null;[\s\S]*?renderBag\(\);\n\}/.test(page) && /bagTab = b\.dataset\.bagtab; makeOrder = null;/.test(page), "opening the Bag and changing its tab start the order afresh");
ok(new Set(first).size === RULES.recipes.length, "every recipe in the book is listed, once");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
