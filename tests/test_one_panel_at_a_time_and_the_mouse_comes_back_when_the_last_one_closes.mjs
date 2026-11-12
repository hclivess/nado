/*
 * test_one_panel_at_a_time_and_the_mouse_comes_back_when_the_last_one_closes.mjs — #179 (playtest 2026-11-11: the Map
 * opened with the mouse still captured, E opened the Bag under a townsperson, every close needed one more click on the
 * world, the hotbar stayed "Earth" after a switch to Čeština). static/land.js read as text:
 *   1. one function opens and closes every panel (showPanel): opening one hides the others and frees the mouse; closing
 *      the last one recaptures it — not on a phone, not with the console open, not under the death card;
 *   2. every panel's open and close site goes through it — no raw hidden toggle on a panel is left; the death path
 *      (closePanels) hides them all and never recaptures (the card is about to show);
 *   3. Escape with a panel open closes them all and gives the mouse back; with none open it does nothing of its own;
 *   4. a language change (i18n.js's nado-lang event) re-renders the hotbar, the piece line, the health line and the plot
 *      card.
 * Run: node tests/test_one_panel_at_a_time_and_the_mouse_comes_back_when_the_last_one_closes.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const PANELS = ["palette", "setPanel", "mapPanel", "wardPanel", "planetPanel", "chestPanel", "machPanel", "npcPanel", "padPanel"];

// 1. showPanel
const sp = land.slice(land.indexOf("function showPanel(id, open)"), land.indexOf("function closePanels()"));
ok(/const PANELS = \["palette", "setPanel", "mapPanel", "wardPanel", "planetPanel", "chestPanel", "machPanel", "npcPanel", "padPanel"\];/.test(land), "the nine panels are named in one list");
ok(/if \(open\) \{\n    for \(const o of PANELS\) if \(o !== id\) hidePanel\(o\);\n    const el = \$\(id\); if \(el\) el\.classList\.remove\("hidden"\);\n    if \(document\.pointerLockElement\) document\.exitPointerLock\(\);/.test(sp), "opening a panel hides every other and frees the mouse");
ok(/\} else \{\n    hidePanel\(id\);\n    if \(!anyPanelOpen\(\) && !conOpen && !touch && \$\("deathCard"\)\.classList\.contains\("hidden"\)\) lockPointer\(\);/.test(sp), "closing the last panel gives the mouse back — not on a phone, not with the console open, not under the death card");
const hp = land.slice(land.indexOf("function hidePanel(id)"), land.indexOf("function showPanel(id, open)"));
ok(/if \(id === "chestPanel"\) chest = null; else if \(id === "machPanel"\) machine = null; else if \(id === "npcPanel"\) talkingTo = null; else if \(id === "padPanel"\) pad = null;/.test(hp), "hiding a panel clears what it was open on (the chest, machine, person, pad)");

// 2. every site goes through it
const raw = land.split("\n").filter((l) => new RegExp(`\\$\\("(${PANELS.join("|")})"\\)\\.classList\\.(remove|add|toggle)\\("hidden"`).test(l));
ok(raw.length === 0, `no raw hidden toggle on a panel is left (${raw.length})` + (raw.length ? ": " + raw[0].trim().slice(0, 100) : ""));
ok(["palette", "settings", "mapPanel", "wardrobe", "planetPanel"].every((fn) => new RegExp(`function ${fn}\\(open\\) \\{\\n  showPanel\\("[A-Za-z]+", open\\);`).test(land)), "the bag, settings, map, wardrobe and planet panels open and close through showPanel");
ok(["npcPanel", "machPanel", "padPanel", "chestPanel"].every((id) => land.includes(`showPanel("${id}", true);`)), "a townsperson, a machine, a launch pad and a chest open through it");
ok(/\$\("chestClose"\)\.onclick = \(\) => showPanel\("chestPanel", false\);/.test(land) && /\$\("npcClose"\)\.onclick = \(\) => showPanel\("npcPanel", false\);/.test(land) && /\$\("machClose"\)\.onclick = \(\) => showPanel\("machPanel", false\);/.test(land) && /\$\("padClose"\)\.onclick = \(\) => showPanel\("padPanel", false\);/.test(land), "…and their Close buttons close through it (the mouse comes back)");
const cp = land.slice(land.indexOf("function closePanels()"), land.indexOf("function closePanels()") + 200);
ok(/for \(const id of PANELS\) hidePanel\(id\);\n  conShow\(false\);\n\}/.test(cp) && !/lockPointer/.test(cp), "closePanels (death) hides them all and never recaptures the mouse");

// 3. Escape
ok(/if \(e\.code === "Escape" && anyPanelOpen\(\)\) \{ closePanels\(\); if \(!touch && \$\("deathCard"\)\.classList\.contains\("hidden"\)\) lockPointer\(\); \}/.test(land), "Escape with a panel open closes them all and gives the mouse back; with none open it leaves the browser's own Escape alone");

// 4. a language change
ok(/window\.addEventListener\("nado-lang", \(\) => \{ hotbar\(\); pieceInfo\(\); if \(lastHp != null\) showHp\(lastHp\); const st = \$\("hudPlot"\); if \(st\) st\.dataset\.html = ""; \}\);/.test(land) && /lastHp = hp;/.test(land), "a language change re-renders the hotbar, the piece line, the health line and the plot card");
ok(/window\.dispatchEvent\(new CustomEvent\("nado-lang"/.test(readFileSync(join(ROOT, "static", "i18n.js"), "utf8")), "…and i18n.js announces the change on window");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
