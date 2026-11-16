/*
 * test_a_phone_buttons_label_fits_inside_it_in_every_language.mjs — playtest 2026-11-16, the phone layout in Russian:
 * "Использовать" (Use) ran across into "Сломать" (Break) beside it, read as one word, and "Поставить" into "Полёт".
 * land.js fitTouchLabels measures the longest word of each round button's label and sets a label wider than the button
 * smaller, never under TOUCH_MIN_PX; one that fits keeps its size. It runs when the buttons are made, again once the
 * labels are in the page's language, and on every language change. Here the page's function runs over every language's
 * labels with a measure of the button's own font (a stand-in canvas: width = characters × the font's average advance).
 * Run: node tests/test_a_phone_buttons_label_fits_inside_it_in_every_language.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("const TOUCH_MIN_PX = "), src = page.slice(i0, page.indexOf("\n}\n", page.indexOf("function fitTouchLabels()", i0)) + 2);
const ADV = 0.62;                                   // a bold sans-serif's average advance, of the font size
const ctx = { font: "", measureText(t) { const px = parseFloat(this.font.split(" ")[1]); return { width: t.length * px * ADV }; } };
const ids = [...html.matchAll(/<button id="(t[A-Z][a-zA-Z]*)" data-i18n="land\.(t[A-Z][a-zA-Z]*)">/g)].map((m) => m[2]).filter((k) => I.en["land." + k]);
const W = Number((html.match(/#touchUi button\{position:fixed;z-index:5;width:(\d+)px/) || [])[1]);
ok(W === 58 && ids.length >= 12, `the round buttons are ${W} px across (${ids.length} labelled ones)`);
let worst = null, tiny = 0, unchanged = 0;
for (const [lang, t] of Object.entries(I)) {
  const buttons = ids.map((k) => ({ textContent: t["land." + k], clientWidth: W, style: { fontSize: "" } }));
  const run = new Function("document", "getComputedStyle", src + "\nreturn fitTouchLabels;")(
    { querySelectorAll: () => buttons, createElement: () => ({ getContext: () => ctx }) }, () => ({ fontSize: "12px", fontWeight: "800", fontFamily: "sans-serif" }));
  run();
  for (const b of buttons) {
    const px = b.style.fontSize ? parseFloat(b.style.fontSize) : 12, w = Math.max(...b.textContent.trim().split(/\s+/).map((x) => x.length * px * ADV));
    if (!b.style.fontSize) unchanged++;
    if (px < 7) tiny++;
    if (w > W - 8 + 0.5 && px > 7) worst = `${lang} "${b.textContent}" ${w.toFixed(0)} px at ${px} px`;
  }
}
ok(!worst, worst ? `a label still wider than its button: ${worst}` : "in all 17 languages every label's longest word fits inside its button (or is at the smallest size)");
ok(tiny === 0, "…none set under the smallest size");
ok(unchanged > ids.length * 17 * 0.7, `…and most labels keep their 12 px (${unchanged} of ${ids.length * 17})`);
ok(/fitTouchLabels\(\); setTimeout\(fitTouchLabels, 1500\);/.test(page) && /relabelNpcs\(\); if \(touch\) fitTouchLabels\(\); \}\);/.test(page), "it runs when the buttons are made, again once the labels are translated, and on every language change");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
