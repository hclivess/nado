/*
 * test_a_boarded_craft_tears_the_trees_it_already_stands_in.mjs — playtest 2026-11-16: the X fighter, parked at
 * 0·4729·4162, had a pine standing through it (photographed at the plot's noon). A craft tears the trees its body meets
 * as it MOVES, and the tears go from the pilot's page: that page closed in the last dive (the trace ends at 191 m, the
 * craft's last pose 3 s later at the ground), so the tree it came to rest in was never sent. Now, once a boarding, when
 * the plots under the craft hold their edits, the body at rest tears what it stands in (the same craftHits / tearCells as
 * in flight). The page's code runs here with stand-ins for the world.
 * Run: node tests/test_a_boarded_craft_tears_the_trees_it_already_stands_in.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const pu = page.slice(page.indexOf("function plotsUnder(c) {"), page.indexOf("\n}\n", page.indexOf("function plotsUnder(c) {")) + 2);
const i0 = page.indexOf("  if (!c.cleared && plotsUnder(c).every((p) => plotsApplied.has(p))) {");
const br = page.slice(i0, page.indexOf("\n  }\n", i0) + 4);
ok(i0 > 0 && page.indexOf("if (torn.size) tearCells(c, torn);") < i0 && i0 < page.indexOf("cannonTick(c, input.slots || heldSlots());"), "the check runs in the flight step, after the step's own tears");
const pose = [0, 66600.8, 75674.3, 118.4, 1.9, 0, 0];
const run = (c, applied, inside) => {
  const torn = [];
  const env = { Wd, W: Wd.W ?? (1 << 17), plotsApplied: new Set(applied), tearCells: (cc, set) => torn.push([...set]),
    craftHits: () => { for (const k of inside) env.box.tearing.add(k); return []; }, box: {} };
  const f = new Function("c", "Wd", "W", "plotsApplied", "tearCells", "craftHitsInner", "box",
    `let tearing = null; const craftHits = (cc, p) => { box.tearing = tearing; return craftHitsInner(cc, p); };\n${pu}\n${br}\nreturn plotsUnder(c);`);
  const under = f(c, Wd, env.W, env.plotsApplied, env.tearCells, env.craftHits, env.box);
  return { torn, under };
};
const pine = ["0:66601:75669:120", "0:66601:75669:121"];
const c = { pose, bodyR: 6 };
const { under } = run({ ...c }, [], []);
ok(under.length >= 1 && under.includes(Wd.plotOf(0, 66600, 75674)), `the plots under the craft (${under.length}) include the one it stands on`);
const c1 = { ...c };
let r = run(c1, [], pine);
ok(r.torn.length === 0 && !c1.cleared, "before the plots' edits are in, nothing is torn (a tree already torn would be no tree)");
r = run(c1, under, pine);
ok(r.torn.length === 1 && r.torn[0].join() === pine.join() && c1.cleared === true, "once they are in, the trunk cells the body stands in are torn, the craft's own way");
r = run(c1, under, pine);
ok(r.torn.length === 0, "…once a boarding, not every step");
const c2 = { ...c };
r = run(c2, under, []);
ok(r.torn.length === 0 && c2.cleared === true, "a craft standing clear sends nothing");
ok(/flying = \{ id: c\.id,/.test(page) && !/cleared: true/.test(page.slice(page.indexOf("function startFlying(c)"), page.indexOf("function startFlying(c)") + 1500)), "every boarding starts a new flying record, so the check runs again on the next boarding or reload");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
