/*
 * test_the_hud_does_not_call_a_plot_wilderness_before_its_owner_is_known.mjs — playtest 2026-11-15 (#199): for the
 * first seconds after a load, before the titles were in, the HUD called the operator's titled plot "Wilderness" —
 * "Unowned: anyone may gather and build here". Until the first answer (titlesVer 0; it bumps even for an empty one) the
 * HUD says it is looking up who owns the plot; after it, an untitled plot is Wilderness as before. The page's own hud
 * branch runs here.
 * Run: node tests/test_the_hud_does_not_call_a_plot_wilderness_before_its_owner_is_known.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf("  if (!t && !titlesVer) html = "), b = page.indexOf("\n  else if (builds.has(plot)", a);
const branch = page.slice(a, b);
const run = (titlesVer) => new Function("t", "titlesVer", "esc", "T", "signIn", "let html;\n" + branch + "\nreturn html;")(undefined, titlesVer, (x) => x, (k, d) => d, "");
ok(a > 0 && /Looking up who owns this plot…/.test(run(0)) && !/Wilderness/.test(run(0)), "before the titles are in, an untitled-looking plot reads \"Looking up who owns this plot…\", not Wilderness");
ok(/Wilderness/.test(run(1)) && /Unowned: anyone may gather and build here/.test(run(1)), "…after the first answer, a plot with no title is Wilderness");
ok(/^let titlesVer = 0, titlesSig = "";/m.test(page) && page.indexOf("let titlesVer = 0") < page.indexOf("function hud()"), "the titles' version is declared before hud (a call before its line would not throw)");
ok(/if \(sig !== titlesSig\) \{ titlesSig = sig; titlesVer\+\+; \}/.test(page), "…and the first answer bumps it, empty or not");
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => typeof t["land.plotLooking"] === "string" && t["land.plotLooking"].length > 5), "in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
