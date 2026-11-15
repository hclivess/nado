/*
 * test_the_goal_line_names_the_key_a_phone_has_not_q.mjs — playtest 2026-11-15, the phone layout: the stone errand done,
 * the goal line said "Done — hand it in to Maren (Elder) … (walk up and press Q)". A phone has no Q; its button is Use
 * (which talks to a person aimed at — useDoor → openNpc). Both goal lines that name the key ("First: talk to …" and
 * "Done — hand it in …") take it as {k}: Use on a touch screen, Q on a keyboard — as the aim line already did — in all
 * 17 languages, none with a Q of its own left in it.
 * Run: node tests/test_the_goal_line_names_the_key_a_phone_has_not_q.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
ok(/const k = touch \? T\("tUse", "Use"\) : "Q";\n    text = q\.ready \? T\("goalReadyAt", "Done — hand it in to \{who\}: \{q\} \(walk up and press \{k\}\)", \{ who: questEnd\(q\), q: questText\(q\), k \}\)/.test(page),
  "the hand-in line names the key: Use on a phone, Q on a keyboard");
ok(/T\("goalTalk", "First: talk to \{who\} — walk up and press \{k\}\. There is work\.", \{ who: [^}]*\}\)`?, k: touch \? T\("tUse", "Use"\) : "Q" \}\)/.test(page) || /k: touch \? T\("tUse", "Use"\) : "Q" \}\)/.test(page.slice(page.indexOf('T("goalTalk"'), page.indexOf('T("goalTalk"') + 300)),
  "…and so does the first errand's line");
ok(/\$\("tUse"\)\.onclick = \(\) => useDoor\(\);/.test(page) && /\{ const n = npcAimed\(\); if \(n\) return openNpc\(n\); \}/.test(page.slice(page.indexOf("function useDoor()"), page.indexOf("function useDoor()") + 1200)),
  "the phone's Use button does talk to the person aimed at");
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => ["land.goalTalk", "land.goalReadyAt"].every((k) => t[k].split("{k}").length === 2 && !t[k].includes("Q"))),
  "both lines in all 17 languages take the key as {k}, no Q left in any");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
