/*
 * test_a_recipe_that_needs_water_says_where_the_nearest_water_is.mjs — WHERE THE WATER IS (#206, playtest 2026-11-16:
 * bread wanted water, the nearest was the sea 1.8 km from the town hall, and nothing in the game said so). The page's own
 * nearestWater and waterHint, lifted from land.js and run against the planet's generator:
 *   1. a recipe that needs water the player lacks says so — first that it is looking, then how far the nearest water is
 *      and which way; a recipe without water, or a player with enough, says nothing;
 *   2. from the town hall the answer is the sea the plain scan finds (1.8 km, south-west), its bearing clockwise from north;
 *   3. the search runs in slices (a phone never stalls) and redraws the bag when it ends; the answer is kept for the 64 m
 *      square the player stands in, and a move out of it starts a new one;
 *   4. where there is no water within the search, it says a well gives it — and the three lines are in 17 languages.
 * Run: node tests/test_a_recipe_that_needs_water_says_where_the_nearest_water_is.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const a = page.indexOf("const WATER_RINGS"), b = page.indexOf("function renderBag() {");
ok(a > 0 && b > a, "the page carries the water search just before the bag");
const src = page.slice(a, b);
const make = (rings) => {
  const env = { P: { face: 0, u: 55128.5, v: 80000.5 }, inv: { items: {} }, redraws: 0 };
  const T = (k, d, o) => (d || "").replace(/\{(\w+)\}/g, (_, x) => (o && o[x] !== undefined ? o[x] : "{" + x + "}"));
  const code = src.replace("const WATER_RINGS = 200", "const WATER_RINGS = " + rings)
    + "\nreturn { nearestWater, waterHint, get job() { return waterNear; } };";
  const f = new Function("P", "Wd", "inv", "T", "bagOpen", "renderBag", code);
  env.api = f(env.P, Wd, env.inv, T, () => true, () => { env.redraws++; });
  return env;
};
const until = async (fn, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(20); } return false; };

// 1-2. from the town hall
const E = make(200);
const bread = { id: "bread", uses: [["flour", 2], ["water", 1]] }, planks = { id: "planks", uses: [["wood", 1]] };
ok(E.api.waterHint(planks) === "", "a recipe without water says nothing about water");
const first = E.api.waterHint(bread);
ok(/looking for the nearest water/.test(first), "a recipe needing water the player lacks says it is looking: " + first);
ok(await until(() => E.api.job.res !== undefined), "…and the search ends");
const w = E.api.job.res;
// the plain scan, cell by cell outward on the same 16 m grid
let best = null;
for (let du = -150; du <= 150; du++) for (let dv = -150; dv <= 150; dv++) {
  const u = 55128 + du * 16, v = 80000 + dv * 16;
  if (Wd.column(0, u, v).top < Wd.SEA) { const d = Math.hypot(u - 55128.5, v - 80000.5); if (!best || d < best) best = d; }
}
ok(w && Math.abs(w.d - best) <= 16 * Math.SQRT2, `from the town hall the nearest water is the sea the plain scan finds: ${w && w.d} m (scan ${Math.round(best)} m)`);
ok(w && w.b > 180 && w.b < 270, `…to the south-west, bearing ${w && w.b}° clockwise from north`);
ok(E.redraws >= 1, "…and the bag is redrawn when the answer comes");
const told = E.api.waterHint(bread);
ok(told.includes(`${w.d} m away, bearing ${w.b}°`) && /a bucket draws it/.test(told), "the recipe line then says how far and which way: " + told);
E.inv.items.water = 1;
ok(E.api.waterHint(bread) === "", "…and nothing once the player carries the water it needs");
E.inv.items.water = 0;
// 3. in slices, kept per 64 m square
ok(/for \(let n = 0; n < WATER_SLICE; n\+\+\)/.test(src) && /setTimeout\(step, 0\)/.test(src) && /WATER_SLICE = 1500/.test(src), "the search runs in slices of 1,500 columns, yielding between them");
const job = E.api.job; E.P.u += 20;
ok(E.api.nearestWater() === w && E.api.job === job, "a step within the same 64 m square keeps the answer");
E.P.u += 64;
ok(E.api.nearestWater() === undefined && E.api.job !== job, "…a move out of it starts a new search");
await until(() => E.api.job.res !== undefined);
// 4. none within the search
const N = make(3);
N.api.nearestWater();
ok(await until(() => N.api.job.res !== undefined) && N.api.job.res === null, "with no water within the search the answer is none");
ok(/a well gives it/.test(N.api.waterHint(bread)), "…and the line says a well gives it: " + N.api.waterHint(bread));
ok(page.includes("+ waterHint(r);"), "the bag's recipe line carries the hint");
const L = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(Object.keys(L).length === 17 && Object.values(L).every((t) => t["land.waterLook"] && t["land.waterNone"] && /\{d\}/.test(t["land.waterAt"]) && /\{b\}/.test(t["land.waterAt"])),
  "the three lines are in all 17 languages, with the distance and the bearing in each");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
