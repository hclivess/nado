/*
 * test_a_level_gained_is_said_and_level_two_names_what_it_opens.mjs — playtest 2026-11-16: a parcel delivered to Tobin
 * lifted the town agent to level 2 and the page said only "Done: +15 experience" — the HUD's number changed, nothing said
 * that the elder now offers hunts and jobs that need tools (land_server.py _new_quest: under level 2 only the hand list,
 * no hunt; from level 2 the whole book). When the bag's update raises the level the page says so, after the hand-in's
 * own notice: level 2 names what it opens, a higher level only itself; the first update after loading says nothing.
 * The page's own "inv" branch runs here with stand-ins.
 * Run: node tests/test_a_level_gained_is_said_and_level_two_names_what_it_opens.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const server = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf('    } else if (m.t === "inv") {'), b = page.indexOf('    } else if (m.t === "offers") {', a);
const body = page.slice(page.indexOf("{", a) + 1, b);
const make = () => {
  const said = [], timers = [], st = { inv: { items: {}, tools: [], stations: [], level: 1 }, invSeen: false };
  const run = new Function("m", "st", "said", "timers", `
    let inv = st.inv, invSeen = st.invSeen, fedUntil = 0;
    const pickup = () => {}, sound = { cue() {} }, showHp = () => {}, fillHot = () => {}, hotbar = () => {}, bagOpen = () => false, renderBag = () => {}, renderWard = () => {};
    const $ = () => ({ classList: { contains: () => true } }), performance = { now: () => 0 };
    const okBar = (t) => said.push(t), setTimeout = (f, ms) => timers.push([f, ms]);
    const T = (k, d, o) => d.replace(/\\{(\\w+)\\}/g, (_, x) => (o || {})[x]);
    ${body}
    st.inv = inv; st.invSeen = invSeen;`);
  return { said, timers, send: (m) => run(m, st, said, timers) };
};
const g = make();
g.send({ level: 1, xp: 90, items: {} });
g.send({ level: 2, xp: 125, items: {} });
ok(g.timers.length === 1 && g.timers[0][1] === 2500, "a level gained is said, 2.5 s after the hand-in's own notice");
g.timers[0][0]();
ok(g.said[0] === "Level 2! The elder now offers all her work — hunts and jobs that need tools.", `level 2 names what it opens: "${g.said[0]}"`);
g.send({ level: 2, xp: 140, items: {} });
ok(g.timers.length === 1, "…an update at the same level says nothing");
g.send({ level: 3, xp: 300, items: {} }); g.timers[1][0]();
ok(g.said[1] === "Level 3!", "a higher level names only itself");
const f = make(); f.send({ level: 4, xp: 700, items: {} });
ok(f.timers.length === 0, "the first update after loading (the level the player already had) says nothing");
ok(/kinds = \["bring", "bring", "deliver"\] if level < 2 else \["bring", "bring", "hunt", "deliver"\]/.test(server) && /self\.hand_bring\(\) if level < 2 else Q\["bring"\]/.test(server),
  "the level-2 message is true: from level 2 the server offers hunts and the whole bring book (tool jobs)");
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => typeof t["land.levelUp2"] === "string" && t["land.levelUp2"].includes("2") && t["land.levelUpN"].includes("{n}")), "both in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
