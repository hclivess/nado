/*
 * test_a_new_player_lands_facing_a_townsperson_and_the_bar_says_what_the_bag_holds.mjs — #178 (the first ten minutes,
 * playtest 2026-11-11: the player appeared nose to the town hall's wall, and the hotbar said "gather something" over a
 * bag full of berries). static/land.js townSpawn and hotbar, read as text beside static/land-recipes.json:
 *   1. the landing's view holds a townsperson: from townSpawn's place and yaw, one of the quests' npcs stands within
 *      8 m and within 35° of straight ahead, and none stands within a body's width of the landing itself;
 *   2. the empty bar names the bag: with things in the bag that cannot be placed, the bar's text is land.bagHeld with
 *      the count, not "gather something"; signed out it still says to sign in;
 *   3. land.bagHeld is in every one of the 17 languages with the count in it, and the languages that bend a noun by
 *      its number (cs, pl, ru, ar) carry their plural forms.
 * Run: node tests/test_a_new_player_lands_facing_a_townsperson_and_the_bar_says_what_the_bag_holds.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the landing's view
const fn = land.slice(land.indexOf("function townSpawn()"), land.indexOf("function load()"));
const m = /return \[q\.face, q\.u0 \+ ([\d.]+), q\.v0 \+ ([\d.]+), (-?Math\.PI \/ 2|0|Math\.PI)\];/.exec(fn);
ok(!!m, "townSpawn returns a place in the town hall's plot and a yaw");
const plotId = Number(/const TOWN_HALL_PLOT = (\d+)/.exec(land)[1]), q = Wd.plotCoords(plotId);
const u = q.u0 + Number(m[1]), v = q.v0 + Number(m[2]), yaw = m[3] === "0" ? 0 : m[3] === "Math.PI" ? Math.PI : -Math.PI / 2;
const fwd = [Math.sin(yaw), Math.cos(yaw)];                 // (land.js: yaw 0 faces +v, sin(yaw) along +u)
const npcs = R.quests.npcs.map((n) => ({ id: n.id, d: [n.at[1] - u, n.at[2] - v] })).map((n) => ({ ...n, dist: Math.hypot(...n.d), ang: Math.acos((n.d[0] * fwd[0] + n.d[1] * fwd[1]) / Math.max(1e-9, Math.hypot(...n.d))) }));
const ahead = npcs.filter((n) => n.dist <= 8 && n.ang <= (35 * Math.PI) / 180);
ok(ahead.length >= 1, `a townsperson stands in the landing's view, within 8 m and 35° of straight ahead: ${ahead.map((n) => `${n.id} ${n.dist.toFixed(1)} m ${(n.ang * 180 / Math.PI).toFixed(0)}°`).join(", ") || "none (" + npcs.map((n) => `${n.id} ${n.dist.toFixed(1)} m ${(n.ang * 180 / Math.PI).toFixed(0)}°`).join(", ") + ")"}`);
ok(npcs.every((n) => n.dist > 0.7), "…and none stands on the landing itself (a body's width clear)");

// 2. the empty bar
const hb = land.slice(land.indexOf("function hotbar()"), land.indexOf("function hotbar()") + 1200);
ok(/const held = net\.me && RULES \? Object\.values\(inv\.items \|\| \{\}\)\.filter\(\(n\) => n > 0\)\.length : 0;/.test(hb)
   && /held \? T\("bagHeld", "[^"]*\{n\}[^"]*", \{ n: held \}\) : T\("emptyHands"/.test(hb) && /!net\.me \? T\("signInGather"/.test(hb),
   "with unplaceable things in the bag the empty bar says land.bagHeld with the count; signed out, sign in; empty, gather");

// 3. seventeen languages
const langs = Object.keys(I);
ok(langs.length === 17 && langs.every((l) => typeof I[l]["land.bagHeld"] === "string" && I[l]["land.bagHeld"].includes("{n}")), `land.bagHeld is in all ${langs.length} languages with the count`);
const forms = (l) => (/\{n\|([^}]*)\}/.exec(I[l]["land.bagHeld"] || "") || ["", ""])[1].split("|").map((f) => f.split(":")[0]);
ok(["cs", "pl", "ru"].every((l) => ["one", "few", "many", "other"].every((f) => forms(l).includes(f))) && ["zero", "one", "two", "few", "many", "other"].every((f) => forms("ar").includes(f)),
   "cs, pl and ru carry one/few/many/other, ar all six forms");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
