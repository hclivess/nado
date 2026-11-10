/*
 * test_a_benchmark_keeps_the_best_graphics_preset_a_device_holds.mjs — THE BENCHMARK'S DECISION (#166: "performance
 * benchmark that sets graphical settings", operator 2026-11-10). static/land-gfx.js, with frame times made up:
 *   1. presets run from Ultra down, each a step lighter (resolution, shadows, view distance) and every value one the
 *      settings accept;
 *   2. a fast device keeps Ultra; a 60 Hz screen pacing 60 fps exactly still holds a 60 fps target;
 *   3. a device that holds only High keeps High; one too slow for all of them keeps Low;
 *   4. a median that holds but a stutter every few frames (p95) does not hold;
 *   5. a phone's target is 30 fps: frames a 60 fps target refuses hold on a phone;
 *   6. too few frames (a tab that stopped drawing) never holds.
 *
 * Run: node tests/test_a_benchmark_keeps_the_best_graphics_preset_a_device_holds.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const G = await import(join(ROOT, "static", "land-gfx.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };
const frames = (ms, n = 60) => Array.from({ length: n }, () => ms);
const withHitches = (ms, every, slow) => Array.from({ length: 60 }, (_, i) => (i % every ? ms : slow));

// 1. the presets
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const range = JSON.parse(("{" + page.match(/const SET_RANGE = \{([\s\S]*?)\};/)[1] + "}").replace(/(\w+):/g, '"$1":'));
ok(G.BENCH_ORDER.join() === "ultra,high,medium,low", "presets are tried from Ultra down");
const keys = ["res", "shadows", "view", "grass", "effects"];
ok(G.BENCH_ORDER.every((n) => keys.every((k) => G.GFX_PRESETS[n][k] >= range[k][0] && G.GFX_PRESETS[n][k] <= range[k][1])), "every preset value is one the settings accept");
ok(G.BENCH_ORDER.slice(1).every((n, i) => { const a = G.GFX_PRESETS[G.BENCH_ORDER[i]], b = G.GFX_PRESETS[n]; return keys.every((k) => b[k] <= a[k]) && keys.some((k) => b[k] < a[k]); }),
  "…each a step lighter than the one before");
ok(page.includes('import { GFX_PRESETS, BENCH_ORDER, benchTarget, frameStats, holds, pickPreset } from "./land-gfx.js";'), "the page uses these presets and this decision");

// 2-3. picking
const T60 = G.benchTarget(false), T30 = G.benchTarget(true);
ok(T60 === 60 && T30 === 30, "a desktop aims at 60 fps, a phone at 30");
ok(G.pickPreset({ ultra: frames(8) }, T60) === "ultra", "a fast device keeps Ultra (measured once)");
ok(G.pickPreset({ ultra: frames(1000 / 60) }, T60) === "ultra", "a 60 Hz screen pacing exactly 60 fps holds a 60 fps target");
ok(G.pickPreset({ ultra: frames(25), high: frames(15) }, T60) === "high", "one that holds only High keeps High");
ok(G.pickPreset({ ultra: frames(90), high: frames(70), medium: frames(50), low: frames(40) }, T60) === "low", "one too slow for all keeps Low");

// 4. stutter
const st = G.frameStats(withHitches(14, 5, 60));
ok(st.p50 <= 16 && !G.holds(st, T60), `a good median with a stutter every 5th frame does not hold (p50 ${st.p50}, p95 ${st.p95} ms)`);
ok(G.holds(G.frameStats(withHitches(14, 40, 60)), T60), "…a rare hitch does");

// 5. a phone
ok(!G.holds(G.frameStats(frames(28)), T60) && G.holds(G.frameStats(frames(28)), T30), "28 ms frames fail a desktop's 60 fps and hold a phone's 30");

// 6. too few frames
ok(G.frameStats([]) === null && !G.holds(G.frameStats([10, 10, 10]), T60), "no frames, or a handful, never hold");
ok(Math.round(G.frameStats(frames(20)).fps) === 50, "frames a second come from the median frame");

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
