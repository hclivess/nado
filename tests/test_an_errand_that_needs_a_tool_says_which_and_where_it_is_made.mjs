/*
 * test_an_errand_that_needs_a_tool_says_which_and_where_it_is_made.mjs — playtest 2026-11-16, a real player's own
 * trace and record: Maren's "Bring 4 × Clay", no tool in their bag, and they flew kilometres from town. Clay is dug
 * only with a shovel; the goal line named no source (the nearest-source hint looks only at what bare hands gather) and
 * nothing said a shovel was the way — while they carried what a stone one is made of. land.js toolFor finds the tool
 * class every source of an item asks for, and goalLine says "it is dug with a Stone shovel — make one in the Bag (Make)"
 * until the player has one (17 languages, the Make tab's own word). The page's toolFor and goalLine run here against
 * the real recipe book.
 * Run: node tests/test_an_errand_that_needs_a_tool_says_which_and_where_it_is_made.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const lang = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const fn = (name) => { const i = page.indexOf(`function ${name}(`); return i < 0 ? "" : page.slice(i, page.indexOf("\n}\n", i) + 2); };
const toolFor = new Function("RULES", fn("toolFor") + "\nreturn toolFor;")(RULES);
ok(toolFor("clay") === "shovel", `clay is dug with a shovel (toolFor: "${toolFor("clay")}")`);
ok(toolFor("berries") === "" && toolFor("sticks") === "" && toolFor("stone") === "", "berries, sticks and stone come by hand: no tool named");
const T = (k, d, a = {}) => d.replace(/\{(\w+)\}/g, (_, n) => a[n]);
const nameOf = (id) => (RULES.items[id] || RULES.tools[id] || {}).name || id;
const run = (tools, have = 0) => {
  const g = { textContent: "-" };
  const inv = { items: { clay: have }, tools, quests: [{ kind: "bring", item: "clay", n: 4 }] };
  const hasClass = (cls) => inv.tools.some((t) => t === cls || (RULES.tools[t] && RULES.tools[t].class === cls));
  new Function("$", "RULES", "net", "inv", "touch", "T", "nameOf", "hasClass", "toolFor", "sourceHint", "questText", "questEnd", "roleName",
    fn("goalLine") + "\ngoalLine();")(() => g, RULES, { me: "x", online: true }, inv, true, T, nameOf, hasClass, toolFor,
    () => "SOURCE HINT", (q) => `Bring ${q.n} × Clay (${have}/${q.n})`, () => "Maren", () => "Elder");
  return g.textContent;
};
const none = run([]);
ok(none === "Your work: Bring 4 × Clay (0/4) · it is dug with a Stone shovel — make one in the Bag (Make).", `no shovel in the bag: "${none}"`);
ok(run(["shovel"]) === "SOURCE HINT" && run(["iron_shovel"]) === "SOURCE HINT", "with any shovel the line goes back to where to find it");
ok(RULES.recipes.some((r) => r.id === "shovel" && r.uses.every(([i]) => ["sticks", "stone", "cordage"].includes(i))), "(a stone shovel is made from sticks, stone and cordage — what that player carried, fibre for the cordage)");
ok(Object.values(lang).every((t) => ["{q}", "{t}", "{m}"].every((x) => (t["land.goalTool"] || "").includes(x))), "the line is in all 17 languages, the work, the tool and the Make tab's word kept");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
