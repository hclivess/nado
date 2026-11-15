/*
 * test_the_phone_fly_button_says_it_is_flying_and_stays_lit_while_it_is.mjs — playtest 2026-11-16 on the phone layout:
 * Fly toggled free flight in silence and the button looked the same either way; F on a keyboard says "Flying — Space up,
 * C down, Shift fast" / "Walking". The phone's Fly now says so with the phone's own buttons ("Flying — Jump to rise,
 * Down to sink; Fly again to walk" / "Walking"), and is lit while flying — kept in step with P.fly every frame, whoever
 * changed it. The message names the very labels on the buttons, in every language.
 * Run: node tests/test_the_phone_fly_button_says_it_is_flying_and_stays_lit_while_it_is.mjs
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
const line = page.split("\n").find((l) => l.includes('$("tFly").onclick = '));
const said = [], P = { fly: false, vh: 3 }, el = {};
new Function("$", "P", "notify", "T", line.trim())((id) => el, P, (m) => said.push(m), (k, d) => d);
el.onclick();
ok(P.fly === true && P.vh === 0 && said[0] === "Flying — Jump to rise, Down to sink; Fly again to walk", `a tap flies and says how, with the phone's buttons: "${said[0]}"`);
el.onclick();
ok(P.fly === false && said[1] === "Walking", "a second tap walks again, and says so");
const sync = page.split("\n").find((l) => l.includes('const fb = $("tFly")'));
const cls = new Set(), fb = { classList: { contains: (c) => cls.has(c), toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)) } };
const step = (fly) => new Function("touch", "$", "P", sync.trim())(true, () => fb, { fly });
step(true); const lit = cls.has("on"); step(false);
ok(lit && !cls.has("on"), "the button is lit while flying and not otherwise, whoever set it (checked each frame)");
ok(/#touchUi button\.on\{border-color:var\(--accent2\);color:var\(--accent2\)\}/.test(html), "…lit as the game's other toggles are");
ok(Object.keys(I).length === 17 && Object.entries(I).every(([, t]) => ["land.tJump", "land.tDown", "land.tFly"].every((k) => t["land.flyOnTouch"].toLowerCase().includes(t[k].toLowerCase()))),
  "in all 17 languages the message names the labels on the phone's own Jump, Down and Fly buttons");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
