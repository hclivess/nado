/*
 * test_the_wardrobe_names_the_plain_clothes_a_figure_wears_when_nothing_is_put_on.mjs — playtest 2026-11-15 (phone
 * layout): the wardrobe listed Body "nothing" and Legs "nothing" beside a figure in a pink shirt and dark trousers. With
 * nothing worn the figure is not bare: lookColours dresses the body in its own `under` colour and the legs grey. Those
 * two slots now read "your own plain clothes"; head and back, drawn with nothing when empty, still say "nothing". The
 * page's lookColours runs here.
 * Run: node tests/test_the_wardrobe_names_the_plain_clothes_a_figure_wears_when_nothing_is_put_on.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
class Color { setHSL() { this.v = 0x123456; return this; } getHex() { return this.v; } }
const i0 = page.indexOf("function lookColours(seed, look) {"), src = page.slice(i0, page.indexOf("\n}\n", i0) + 2);
const lookColours = new Function("THREE", "SKIN", "HAIR", "WEAR", src + "\nreturn lookColours;")({ Color }, [1], [2], { shirt: 9 });
const c = lookColours("3fd1b6", { worn: {} });
ok(c.top != null && c.legs != null && c.cap === null && c.cloak === null, "with nothing worn the figure still has a shirt and legwear of its own colours, and no cap or cloak");
ok(/const PLAIN_SLOTS = new Set\(\["body", "legs"\]\);/.test(page) && /PLAIN_SLOTS\.has\(slot\) \? T\("wPlain", "your own plain clothes"\) : T\("wNothing", "nothing"\)/.test(page),
  "so an empty body or legs slot reads \"your own plain clothes\"; head and back \"nothing\"");
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => typeof t["land.wPlain"] === "string" && t["land.wPlain"].length > 3), "in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
