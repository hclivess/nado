/*
 * test_a_torch_in_hand_lights_a_pool_brighter_than_the_moon_round_the_player.mjs — #181 item 1, checked on the live page
 * 2026-11-15 at night: the same view with and without the torch in hand differed by ~9 % and showed no warm pool. The
 * torch in hand was a placed torch's light (3), and the moon (MOON_I 1.3) lights the ground about as much at the 1.5 m
 * under the hand. TORCH_IN_HAND (a game rule): within 3 m of the hand the carried torch outshines the moon (i / 3² ≥
 * MOON_I, the light falling off with the square of distance, three's decay 2) and it is back to moonlight by ~4 m.
 * Run: node tests/test_a_torch_in_hand_lights_a_pool_brighter_than_the_moon_round_the_player.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const moon = Number((page.match(/const MOON_I = ([\d.]+)/) || [])[1]);
const carried = page.match(/carried: \{ i: ([\d.]+), d: ([\d.]+),/);
const i = Number(carried && carried[1]), d = Number(carried && carried[2]);
ok(moon > 0 && i > 0, `the moon's light (${moon}) and the carried torch's (${i}) are read from the page`);
ok(i / 9 >= moon, `within 3 m of the hand the torch outshines the moon (${(i / 9).toFixed(2)} ≥ ${moon})`);
ok(i / 16 <= moon * 1.2, `…and by 4 m it is back to about moonlight (${(i / 16).toFixed(2)} against ${moon}) — a pool, not a floodlight`);
ok(i / 2.25 >= 4 * moon, `under the hand (1.5 m) it is several times the moon (${(i / 2.25).toFixed(1)}): a warm pool to walk in`);
ok(d >= 4, "its reach takes in the whole pool");
ok(/new THREE\.PointLight\(0xffa04a, 0, 9, 2\)/.test(page), "the light falls off with the square of distance (decay 2), as the rule assumes");
ok(/TORCH_IN_HAND \(a game rule, not a measured flame\)/.test(page), "the number is labelled a game rule");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
