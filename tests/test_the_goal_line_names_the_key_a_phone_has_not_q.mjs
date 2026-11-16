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
{ // the elder's line, run: the key by name — and "First:" only to a newcomer; a player with experience is told there is
  // MORE work (playtest 2026-11-16: the town agent, level 2, was told "First: talk to Maren" on every load)
  const gl = page.slice(page.indexOf("function goalLine() {"), page.indexOf("\n}\n", page.indexOf("function goalLine() {")) + 2);
  const run = (touch, xp) => {
    const g = { textContent: "" };
    const T = (k, d, a = {}) => k + ":" + d.replace(/\{(\w+)\}/g, (_, n) => a[n]);
    new Function("$", "RULES", "net", "inv", "touch", "T", "roleName", gl + "\ngoalLine();")(() => g,
      { quests: { npcs: [{ id: "maren", name: "Maren", role: "elder" }] } }, { me: "x" }, { quests: [], xp }, touch, T, () => "Elder");
    return g.textContent;
  };
  ok(run(true, 0).startsWith("goalTalk:First: talk to Maren (Elder)") && run(true, 0).includes("press tUse:Use") && run(false, 0).includes("press Q"),
    "…and so does the first errand's line: a newcomer is told First: talk to the elder, Use on a phone, Q on a keyboard");
  ok(run(true, 125).startsWith("goalTalkMore:More work: talk to Maren (Elder)") && run(true, 125).includes("press tUse:Use") && run(false, 125).includes("press Q") && !run(false, 125).includes("First"),
    "…a player who has earned experience is told MORE work, not First:");
}
ok(/\$\("tUse"\)\.onclick = \(\) => useDoor\(\);/.test(page) && /\{ const n = npcAimed\(\); if \(n\) return openNpc\(n\); \}/.test(page.slice(page.indexOf("function useDoor()"), page.indexOf("function useDoor()") + 1200)),
  "the phone's Use button does talk to the person aimed at");
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => ["land.goalTalk", "land.goalReadyAt"].every((k) => t[k].split("{k}").length === 2 && !t[k].includes("Q"))),
  "both lines in all 17 languages take the key as {k}, no Q left in any");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
