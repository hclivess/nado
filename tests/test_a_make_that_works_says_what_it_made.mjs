/*
 * test_a_make_that_works_says_what_it_made.mjs — playtest 2026-11-16, the town agent's phone page: Bag → Make → "Make"
 * on planks turned a wood into four planks and said nothing. The Bag covers the screen, and a count changing on the
 * hotbar under it was the only sign the tap did anything. The world server answers every craft with "done" (an error or
 * none); the page said only the error. land.js now remembers which recipe a request made (net.made) and, on a "done"
 * without an error, says "Made 4 × Planks." (land.madeIt, 17 languages). The page's own branch runs here.
 * Run: node tests/test_a_make_that_works_says_what_it_made.mjs
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
// the "done" branch of the socket handler, as the page has it
const i0 = page.indexOf('} else if (m.t === "done") {'), i1 = page.indexOf('} else if (m.t === "set_ok") {', i0);
ok(i0 > 0 && i1 > i0, "(the page handles the world server's done)");
const branch = page.slice(i0 + '} else if (m.t === "done") {'.length, i1);
const run = (m, made) => {
  const said = { ok: [], err: [] };
  const net = { made: new Map(made ? [[m.req, made]] : []) };
  const T = (k, d, a = {}) => d.replace(/\{(\w+)\}/g, (_, n) => a[n]);
  const nameOf = (id) => (RULES.items[id] || {}).name || id;
  new Function("m", "net", "RULES", "T", "nameOf", "okBar", "notify", branch)(m, net, RULES, T, nameOf, (x) => said.ok.push(x), (x) => said.err.push(x));
  return { said, left: net.made.size };
};
const a = run({ t: "done", req: 7, error: null }, "planks");
ok(a.said.ok.length === 1 && a.said.ok[0] === "Made 4 × Planks." && !a.said.err.length, `a make that works says what it made: "${a.said.ok[0]}"`);
ok(a.left === 0, "…and forgets the request");
const b = run({ t: "done", req: 8, error: "needs 1 × Wood" }, "planks");
ok(!b.said.ok.length && b.said.err[0] === "needs 1 × Wood" && b.left === 0, "a refused make says only why");
const c = run({ t: "done", req: 9, error: null }, null);
ok(!c.said.ok.length && !c.said.err.length, "a done for something else (a gift, an offer) says no 'Made'");
ok(/b\.onclick = \(\) => \{ req\(\{ t: "craft", recipe: b\.dataset\.make \}\); net\.made\.set\(net\.req, b\.dataset\.make\); \};/.test(page) && /pending: new Map\(\), made: new Map\(\)/.test(page),
  "the Bag's Make button remembers the recipe under the request's number");
ok(Object.values(lang).every((t) => typeof t["land.madeIt"] === "string" && t["land.madeIt"].includes("{what}")), "the line is in all 17 languages, its {what} kept");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
