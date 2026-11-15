/*
 * test_lands_rule_numbers_are_named_rules_or_cited_to_their_source.mjs — the operator (2026-11-10): "don't do anything
 * from memory" (#170). A Land number that looks like the world's is either cited where it stands or named a game rule.
 * This pins the ones settled so far:
 *   1. health and food (land-recipes.json): every number in the section is named a game rule in its own "about";
 *   2. the pace of free flight (land_server.py PACE_MPS, land.js FLY / FLY_FAST): named game rules beside the numbers;
 *   3. the graphics governor (land-gfx.js GOV): cited to True Wind's js/gfx.js AUTO, with its numbers, and slowK / fastK
 *      are those of its 26 and 15.5 ms at a 60 fps frame (16.7 ms) to two places.
 * Hunting, farming and flight's thrust and densities are still to be sourced (#170 stays open for them).
 * Run: node tests/test_lands_rule_numbers_are_named_rules_or_cited_to_their_source.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const srv = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8"), page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const gfxSrc = readFileSync(join(ROOT, "static", "land-gfx.js"), "utf8"), G = await import(join(ROOT, "static", "land-gfx.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

ok(["health", "food"].every((k) => /Every number in this section is a GAME RULE chosen for play, not a measurement of the world\./.test(R[k].about)), "1. health and food name every number in them a game rule");
ok(/PACE_MPS, PACE_SLACK, PACE_DT_MAX = [^\n]*\n# \(#170: GAME RULES, not measurements/.test(srv), "2. the world server's pace of free flight is named a game rule beside its numbers");
ok(/FLY_FAST = 60;\s+\/\/ \(#170: FLY and FLY_FAST are GAME RULES/.test(page), "…and so is the page's free-flight speed");
ok(/SOURCED \(#170\): True Wind's js\/gfx\.js \(github\.com\/hclivess\/truewind\) AUTO = \{ slow: 26, fast: 15\.5, down: 3, up: 12,/.test(gfxSrc), "3. the governor cites True Wind's AUTO with its numbers");
const frame = 1000 / 60;
ok(Math.abs(G.GOV.slowK - 26 / frame) < 0.01 && Math.abs(G.GOV.fastK - 15.5 / frame) < 0.01 && G.GOV.downS === 3 && G.GOV.upS === 12 && G.GOV.holdS === 4 && G.GOV.helpK === 0.9 && G.GOV.noDownS === 60,
  `…and its numbers are the source's: slowK ${G.GOV.slowK} ≈ 26/16.7 = ${(26 / frame).toFixed(3)}, fastK ${G.GOV.fastK} ≈ 15.5/16.7 = ${(15.5 / frame).toFixed(3)}, down 3 s, up 12 s, hold 4 s, gain 0.9, futile 60 s`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
