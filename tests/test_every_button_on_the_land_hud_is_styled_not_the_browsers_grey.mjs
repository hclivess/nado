/**
 * Every button on Land's HUD has a rule of its own, so none draws as the browser's default grey button.
 *
 * Run: node tests/test_every_button_on_the_land_hud_is_styled_not_the_browsers_grey.mjs
 *
 * The Settings gear (#setBtn, #179) was added beside Map with no CSS rule; on every screen it drew as the
 * browser's own light-grey button with black text next to the dark Map button (playtest 2026-11-17). This reads
 * static/land.html, takes every <button id> inside #hudInfo, and requires a rule naming that id that sets a
 * background and a colour.
 */
import { readFileSync } from "node:fs";
const html = readFileSync(new URL("../static/land.html", import.meta.url), "utf8");
let pass = 0, fail = 0;
const ck = (name, cond, extra = "") => { if (cond) { pass++; console.log("PASS  " + name); } else { fail++; console.log("FAIL  " + name + "  " + extra); } };

const hud = html.match(/<div id="hudInfo">([\s\S]*?)<\/div>\s*\n/);
ck("the HUD block is found in land.html", !!hud);
const ids = hud ? [...hud[1].matchAll(/<button[^>]*\bid="([^"]+)"/g)].map((m) => m[1]) : [];
ck("the HUD carries its buttons (Map and Settings at least)", ids.includes("mapBtn") && ids.includes("setBtn"), ids.join(","));
const css = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n").replace(/\/\*[\s\S]*?\*\//g, "");
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1], body: m[2] }));
for (const id of ids) {
  const own = rules.filter((r) => r.sel.split(",").some((s) => new RegExp("#" + id + "(?![\\w-])").test(s.trim()) && !/[ >+~]/.test(s.trim())));
  ck(`#${id} has a rule that sets its background and colour`, own.some((r) => /background\s*:/.test(r.body) && /(^|;)\s*color\s*:/.test(r.body)), own.map((r) => r.sel.trim()).join(" | ") || "no rule");
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
