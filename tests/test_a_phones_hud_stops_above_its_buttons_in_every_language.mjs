/*
 * test_a_phones_hud_stops_above_its_buttons_in_every_language.mjs — playtest 2026-11-16, the phone layout measured in
 * all 17 languages: in German, signed out, the plot card ("Auf dem Marktplatz ansehen") wrapped onto one more line and
 * Settings ran 1 px into the Fire button. land.js fitHud measures the HUD after every redraw on a phone and, past the
 * top button row less 4 px, gives it its tighter type (.tight — previewed live in German: 139 px against Fire at 194);
 * otherwise its own. The page's fitHud runs here.
 * Run: node tests/test_a_phones_hud_stops_above_its_buttons_in_every_language.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("function fitHud() {"), src = page.slice(i0, page.indexOf("\n}\n", i0) + 2);
const run = (bottomPlain, bottomTight, fireTop) => {
  const cls = new Set(["tight"]);
  const h = { classList: { remove: (c) => cls.delete(c), add: (c) => cls.add(c) }, getBoundingClientRect: () => ({ bottom: cls.has("tight") ? bottomTight : bottomPlain }) };
  // as the real button: position:fixed, so offsetParent null (a stand-in with one hid that fitHud never ran, live)
  const f = { offsetParent: null, getClientRects: () => [{}], getBoundingClientRect: () => ({ top: fireTop }) };
  new Function("$", src + "\nfitHud();")((id) => (id === "hudInfo" ? h : f));
  return cls.has("tight");
};
ok(run(195, 139, 194) === true, "German signed out (195 px against Fire at 194): the HUD takes its tighter type");
ok(run(152, 120, 194) === false, "English (152 px): it keeps its own (a stale .tight is taken off)");
ok(run(191, 150, 194) === true && run(189, 150, 194) === false, "…the line is the button row less 4 px");
ok(/  if \(touch\) fitHud\(\);\n\}/.test(page), "it runs at the end of every HUD redraw, on a phone only");
ok(/body\.touch #hudInfo\.tight\{font-size:10px;line-height:1\.2\}/.test(html), "the tighter type is defined for the phone HUD");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
