/*
 * test_every_name_the_land_page_builds_at_runtime_is_translated_in_17_languages.mjs — the operator (2026-11-14):
 * "translations missing". tests/i18n_coverage.mjs reads the keys written out in the code; the names land.js BUILDS at
 * runtime — T("b." + key), T("i." + id), T("t." + id), T("s." + id), T("part." + type), T("npc." + role), T("a." + kind),
 * T("slot." + slot) — it cannot see, and five block names (lamp and the orange, green, blue and purple cubes) had no
 * translation in any language: the aim line said them in English. This walks every name the page can ask for, by the
 * page's own rules, and checks it in all 17 languages:
 *   - a block is named by the item that places it, else the item of its own name, else land.b.<key> (blockLabel);
 *   - every item, tool and station by land.i / land.t / land.s; every part type; the three townspeople's roles; the
 *     animals the world server keeps; the wardrobe's four slots.
 * Run: node tests/test_every_name_the_land_page_builds_at_runtime_is_translated_in_17_languages.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), Sh = await import(join(ROOT, "static", "land-shapes.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8")), L = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), srv = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const langs = Object.keys(L);
ok(langs.length === 17, `17 languages (${langs.join(" ")})`);
// the page's own rules, read so a change to them is noticed here
ok(page.includes('return id ? nameOf(id) : RULES && RULES.items[k] ? nameOf(k) : T("b." + k, k);'), "blockLabel: the placing item, else the item of its own name, else land.b.<key>");
ok(page.includes('RULES.items[id] ? T("i." + id,') && page.includes('RULES.tools[id] ? T("t." + id,') && page.includes('RULES.stations[id] ? T("s." + id,'), "nameOf: land.i / land.t / land.s");
const kinds = [...new Set([...srv.matchAll(/"kind": "([a-z]+)"/g)].map((m) => m[1]).concat(["deer", "boar", "rabbit"]))];
const need = [];
for (const b of W.BLOCKS) {
  if (b.key === "air") continue;
  const placed = Object.keys(R.items).find((i) => R.items[i].places === W.B[b.key]);
  if (!placed && !R.items[b.key]) need.push("b." + b.key);
}
for (const id of Object.keys(R.items)) need.push("i." + id);
for (const id of Object.keys(R.tools)) need.push("t." + id);
for (const id of Object.keys(R.stations)) need.push("s." + id);
for (const n of Sh.TYPES) need.push("part." + n);
for (const r of ["elder", "trader", "smith"]) need.push("npc." + r);
for (const k of kinds) need.push("a." + k);
for (const s of ["head", "body", "legs", "back"]) need.push("slot." + s);
const missing = need.map((k) => [k, langs.filter((l) => typeof L[l]["land." + k] !== "string" || !L[l]["land." + k].trim())]).filter(([, l]) => l.length);
ok(missing.length === 0, `every one of the ${need.length} names the page builds at runtime is in all 17 languages` + (missing.length ? ": missing " + missing.map(([k, l]) => `${k} (${l.length})`).join(", ") : ""));
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
