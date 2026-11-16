/*
 * test_the_welcome_card_says_q_talks_to_a_person.mjs — playtest 2026-11-16, the desktop welcome card: "Q open or close
 * a door" — but Q is also how a newcomer talks to the townspeople who give the first errands (the aim line says
 * "Maren — Q talk"; useDoor → openNpc), and the card never said so. Q's help names talking first, in the page and in
 * all 17 languages, and Q does talk.
 * Run: node tests/test_the_welcome_card_says_q_talks_to_a_person.mjs
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
ok(/<kbd>Q<\/kbd> <span data-i18n="land\.kDoor">talk to a person, open or close a door<\/span>/.test(html), "the card says Q talks to a person, then opens or closes a door");
ok(I.en["land.kDoor"] === "talk to a person, open or close a door", "…in English");
const old = { cs: "otevřít či zavřít dveře", de: "Tür öffnen oder schließen", ru: "открыть или закрыть дверь", ja: "扉を開け閉め", ar: "فتح باب أو إغلاقه" };
ok(Object.keys(I).length === 17 && Object.entries(I).every(([l, t]) => t["land.kDoor"].length > (old[l] || "").length + 3 && (!old[l] || t["land.kDoor"].includes(old[l]))), "…and in all 17 languages, the door's words kept and talking added");
const ud = page.slice(page.indexOf("function useDoor() {"), page.indexOf("function useDoor() {") + 1400);
ok(/\{ const n = npcAimed\(\); if \(n\) return openNpc\(n\); \}/.test(ud) && /if \(e\.code === "KeyQ"\)|KeyQ/.test(page), "…and Q does talk (useDoor opens the person aimed at)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
