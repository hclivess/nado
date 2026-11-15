/*
 * test_the_phone_button_that_flattens_ground_is_not_called_level.mjs — playtest 2026-11-15 on the phone layout: the
 * button that flattens the ground with a shovel (startLevel, L on a keyboard) was labelled "Level", right under the
 * health line's "Level 1" (the player's experience level) — a player reads it as their level. Every other language
 * already named the work ("Srovnat", "Ebnen", "Niveler", "整地"); English now says "Flatten", in the page and its table.
 * Run: node tests/test_the_phone_button_that_flattens_ground_is_not_called_level.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
ok(/<button id="tLevel" data-i18n="land\.tLevel">Flatten<\/button>/.test(html) && I.en["land.tLevel"] === "Flatten", "the button reads \"Flatten\" in the page and in English");
ok(/\$\("tLevel"\)\.onclick = \(\) => startLevel\(\);/.test(page) && /if \(!hasClass\("shovel"\)\) return notify\(T\("levelNeedsShovel"/.test(page), "…and it is the shovel's flattening of the ground");
ok(Object.entries(I).every(([l, t]) => typeof t["land.tLevel"] === "string" && t["land.tLevel"] !== "Level" && (l === "en" || t["land.tLevel"] !== "Flatten")), "no language calls it \"Level\", and each has its own word");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
