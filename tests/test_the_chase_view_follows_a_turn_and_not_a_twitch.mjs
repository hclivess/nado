// test_the_chase_view_follows_a_turn_and_not_a_twitch.mjs — the X fighter in flight (operator 2026-11-22: "very noisy",
// then: the sound and a shaky camera/motion). The chase camera hung rigidly off the craft's nose and roll 9 m back, so
// every twitch of the attitude moved the whole view. It is now eased (land.js chaseView, CHASE_LAG):
//   1. a nose that twitches 6 degrees for one 60 fps frame and back moves the view less than a quarter of that;
//   2. a held turn of 30 degrees is followed: within half a second the view is within 3 degrees of the nose;
//   3. on foot the view is the look itself, unchanged (no lag walking);
//   4. the frame takes the camera's direction and up from chaseView, and eyePos hangs the camera off the same.
// Run: node tests/test_the_chase_view_follows_a_turn_and_not_a_twitch.mjs
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const a = page.indexOf("const CHASE_LAG"), b = page.indexOf("\n}\n", page.indexOf("function chaseView", a)) + 3;
ok(a > 0 && b > a, "the eased chase view is in the page");
const make = new Function("look", "state", page.slice(a, b).replace(/\bflying\b/g, "state.flying").replace(/\bcraftUp\b/g, "state.craftUp") + "\nreturn chaseView;");
let nose = [0, 1, 0];
const state = { flying: { id: "x" }, craftUp: [0, 0, 1] };
const view = make(() => ({ fr: { up: [0, 0, 1] }, fw: nose }), state);
const deg = (u, v) => Math.acos(Math.max(-1, Math.min(1, u[0] * v[0] + u[1] * v[1] + u[2] * v[2]))) * 180 / Math.PI;
const dir = (d) => [Math.sin(d * Math.PI / 180), Math.cos(d * Math.PI / 180), 0];
for (let i = 0; i < 60; i++) view(1 / 60);                       // settled on the nose
nose = dir(6); let v = view(1 / 60); const twitch = deg(v.fw, dir(0));
nose = dir(0); for (let i = 0; i < 30; i++) v = view(1 / 60);
ok(twitch < 1.5, `1. a 6° twitch for one frame moves the view ${twitch.toFixed(2)}°`);
nose = dir(30); for (let i = 0; i < 30; i++) v = view(1 / 60);
ok(deg(v.fw, dir(30)) < 3, `2. half a second into a held 30° turn the view is ${deg(v.fw, dir(30)).toFixed(2)}° off the nose`);
state.flying = null; nose = dir(77); v = view(1 / 60);
ok(deg(v.fw, dir(77)) < 1e-9, "3. on foot the view is the look itself");
ok(/const \{ fw, up: cu \} = chaseView\(dt\)/.test(page) && /const \{ fw, up \} = chase \|\| chaseView\(0\);/.test(page), "4. the frame and eyePos both take the eased view");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
