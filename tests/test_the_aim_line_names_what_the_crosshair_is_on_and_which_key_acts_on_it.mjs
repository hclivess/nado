/*
 * test_the_aim_line_names_what_the_crosshair_is_on_and_which_key_acts_on_it.mjs — #177 (playtest 2026-11-11: talking
 * to Maren could not be found, a pebble and a boulder looked alike, a refused plot said so only after the whole hold).
 * static/land.js aimText / frame / act, read as text, and the 17 languages:
 *   1. the page has the line under the crosshair and frame() refreshes it from the aim at most ~6×/s;
 *   2. aimText names the thing and the key: a person → "{name} — Q talk"; an animal → the weapon; a door or chest →
 *      open; a bed → sleep; a well → draw water; a seat or a craft's hull → board; a machine or launch pad → use; any
 *      other piece → take down where you may build, else the plot's state and "not yours"; a cell → gather or not
 *      yours; on a phone the key is the Use button and the hold the Break button;
 *   3. a click on a person talks (act() opens them before anything else, left or right button);
 *   4. the twelve strings are in all 17 languages with their placeholders;
 *   5. a plot you may not touch says so BEFORE the hold: startBreak and startTakeDown check mayBuild first and
 *      explainNoBuild names the plot's real state — for sale at its price, or whose it is (two more strings, 17 languages);
 *   6. the outline is dark by day and light by night (from the sky's own day value), and on litter it is the litter's
 *      catch box, not the whole cell;
 *   7. R, G and T with nothing placeable held say what they are for (one string, 17 languages).
 * Run: node tests/test_the_aim_line_names_what_the_crosshair_is_on_and_which_key_acts_on_it.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the line and its refresh
ok(/<div id="cross"><\/div><div id="aimLine"><\/div>/.test(html) && /#aimLine\{position:fixed;left:50%;top:calc\(50% \+ 16px\)/.test(html), "the line sits under the crosshair");
const fr = land.slice(land.indexOf("function frame(now)"), land.indexOf("function frame(now)") + 6000);
ok(/const a = pt\("aim", \(\) => aim\(\)\);\n  if \(now - aimLineAt > 150\) \{ aimLineAt = now; const s = aimText\(a\), el = \$\("aimLine"\);/.test(fr), "frame() refreshes it from the same aim as the outline, at most every 150 ms");

// 2. what it says
const at = land.slice(land.indexOf("function aimText(a)"), land.indexOf("/** The NPC under the crosshair"));
ok(/const k = touch \? T\("tUse", "Use"\) : "Q", b = touch \? T\("tBreak", "Break"\) : T\("kLeft", "left click"\);/.test(at), "the key is Q (the Use button on a phone), the hold the left click (the Break button)");
ok(/const n = npcAimed\(\);\n  if \(n\) \{ const r = npcs\.get\(n\); return T\("aimFmt", "\{what\} — \{k\} \{v\}", \{ what: r \? r\.name : n, k, v: T\("v\.talk", "talk"\) \}\); \}/.test(at), "a person: their name — Q talk (before anything else)");
ok(/animalAimed\(8\)[\s\S]*animalName\(r \? r\.kind : "deer"\), v: T\("v\.hunt"/.test(at), "an animal within 8 m: its kind — a weapon hunts it");
ok(/kind === B\.door \|\| kind === B\.chest \? T\("v\.open"/.test(at) && /kind === B\.bed \? T\("v\.sleep"/.test(at) && /kind === B\.well \? T\("v\.draw"/.test(at)
   && /kind === B\.pilotseat \|\| CRAFT_SKIN\.has\(kind\) \? T\("v\.board"/.test(at) && /kind === B\.generator \|\| kind === B\.launchpad \|\| isMachine\(kind\) \? T\("v\.use"/.test(at),
   "a door or chest — open; a bed — sleep here; a well — draw water; a seat or hull — board; a machine or pad — use");
ok(/return mayBuild\(a\.box\.plot\) \? T\("aimFmt2", "\{what\} — \{v\}", \{ what, v: T\("v\.take", "hold \{b\} to take down", \{ b \}\) \}\) : notYours\(what, a\.box\.plot\);/.test(at), "any other piece: take down where you may build, else not yours");
ok(/const \[u, v, h\] = a\.hit, what = blockLabel\(blockAt\(P\.face, u, v, h\)\), plot = Wd\.plotOf\(P\.face, u, v\);\n  return mayBuild\(plot\) \? T\("aimFmt2", "\{what\} — \{v\}", \{ what, v: T\("v\.gather", "hold \{b\} to gather", \{ b \}\) \}\) : notYours\(what, plot\);/.test(at), "a cell: its name — hold to gather, or not yours");
ok(/const notYours = \(what, plot\) => \{ const t = titles\.get\(plot\); return T\("aimFmt2"[\s\S]*t && t\.sale \? T\("forSale"[\s\S]*t && t\.holder \? T\("owned", "Owned by \{o\}"[\s\S]*: T\("titled", "Titled"\)[\s\S]*v: T\("v\.notYours", "not yours to gather here"\)/.test(at), "…and 'not yours' carries the plot's state: for sale at its price, whose it is, or just titled (never 'Owned by —')");
ok(/^function blockLabel\(b\) \{/m.test(land) && /const named = blockLabel;/.test(land), "the /aim command and the line share one naming of blocks and pieces");

// 3. a click talks
const act = land.slice(land.indexOf("function act(place, mouse)"), land.indexOf("function act(place, mouse)") + 900);
const iTalk = act.indexOf('{ const n = npcAimed(); if (n) return openNpc(n); }'), iAnimal = act.indexOf("animalAimed(RULES"), iSign = act.indexOf('if (!net.me) return notify(T("signInBuild2"');
ok(iSign >= 0 && iTalk > iSign && iAnimal > iTalk && !/if \(!place\) \{ const n = npcAimed/.test(act), "a click on a person — either button — talks, after the sign-in check and before the hunt");

// 4. the languages
const keys = { "land.aimFmt": ["{what}", "{k}", "{v}"], "land.aimFmt2": ["{what}", "{v}"], "land.v.talk": [], "land.v.open": [], "land.v.sleep": [], "land.v.draw": [], "land.v.board": [], "land.v.use": [], "land.v.hunt": [], "land.v.gather": ["{b}"], "land.v.take": ["{b}"], "land.v.notYours": [] };
const langs = Object.keys(I);
ok(langs.length === 17 && Object.entries(keys).every(([k, ph]) => langs.every((l) => typeof I[l][k] === "string" && I[l][k].length > 0 && ph.every((x) => I[l][k].includes(x)))), "the twelve strings are in all 17 languages with their placeholders");

// 5. refused before the hold, with the plot's state
const sb = land.slice(land.indexOf("function startBreak(c, mouse)"), land.indexOf("function startBreak(c, mouse)") + 700);
ok(/if \(c\[2\] >= 0 && !mayBuild\(Wd\.plotOf\(P\.face, c\[0\], c\[1\]\)\)\) return explainNoBuild\(Wd\.plotOf\(P\.face, c\[0\], c\[1\]\)\);/.test(sb) && sb.indexOf("explainNoBuild") < sb.indexOf("RULES.breaking[b]"), "startBreak refuses a plot you may not touch before the hold (the deep excepted)");
const td = land.slice(land.indexOf("function startTakeDown(bx, mouse)"), land.indexOf("function startTakeDown(bx, mouse)") + 300);
ok(/^function startTakeDown\(bx, mouse\) \{\n  if \(!mayBuild\(bx\.plot\)\) return explainNoBuild\(bx\.plot\);/m.test(td), "…and so does taking a piece down");
const en = land.slice(land.indexOf("function explainNoBuild(plot)"), land.indexOf("function explainNoBuild(plot)") + 900);
ok(/t && t\.sale\) notify\(T\("notYoursSale", "[^"]*\{p\}[^"]*\{n\}[^"]*"/.test(en) && /t && t\.holder\) notify\(T\("notYoursOwned", "[^"]*\{p\}[^"]*\{o\}[^"]*"/.test(en) && /T\("notYours", /.test(en), "explainNoBuild says for sale at the price, or whose it is, else the old line");
ok(langs.every((l) => /\{p\}/.test(I[l]["land.notYoursSale"] || "") && /\{n\}/.test(I[l]["land.notYoursSale"] || "") && /\{p\}/.test(I[l]["land.notYoursOwned"] || "") && /\{o\}/.test(I[l]["land.notYoursOwned"] || "")), "the two refusals are in all 17 languages with their placeholders");

// 6. the outline
ok(/dayNow = day;/.test(land) && /highlight\.material\.color\.setScalar\(0\.07 \+ 0\.85 \* \(1 - dayNow\)\);/.test(fr), "the outline's colour follows the sky's day value: dark by day, light by night");
ok(/if \(Wd\.LITTER\.has\(blockAt\(P\.face, a\.hit\[0\], a\.hit\[1\], a\.hit\[2\]\)\)\)\n      frameBox\(highlight, hp, \[\(a\.hit\[0\] - q\.u0 \+ 0\.5 - LITTER_R\) \* Wd\.CM, \(a\.hit\[1\] - q\.v0 \+ 0\.5 - LITTER_R\) \* Wd\.CM, a\.hit\[2\] \* Wd\.CM, 2 \* LITTER_R \* Wd\.CM, 2 \* LITTER_R \* Wd\.CM, LITTER_H \* Wd\.CM\]\);/.test(fr), "on litter the outline is the litter's own catch box (LITTER_R round its middle, LITTER_H high)");

// 7. R, G and T confirm the press
ok(/function pieceInfo\(pressed\) \{[\s\S]*?if \(pressed && !\(id && RULES && !NATURAL_ITEMS\.has\(id\)\)\) notify\(T\("pieceNoItem"/.test(land), "pieceInfo(pressed) says what R/G/T are for when nothing placeable is held");
ok(/if \(e\.code === "KeyR"\)[^\n]*pieceInfo\(true\);/.test(land) && /if \(e\.code === "KeyG"\)[^\n]*pieceInfo\(true\);/.test(land) && /function turnPiece\(\) \{[\s\S]*?pieceInfo\(true\);/.test(land), "…and R, G and T all pass that they were pressed");
ok(langs.every((l) => typeof I[l]["land.pieceNoItem"] === "string" && I[l]["land.pieceNoItem"].length > 10), "the string is in all 17 languages");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
