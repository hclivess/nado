/*
 * test_a_new_player_lands_facing_a_townsperson_and_the_bar_says_what_the_bag_holds.mjs — #178 (the first ten minutes,
 * playtest 2026-11-11: the player appeared nose to the town hall's wall, and the hotbar said "gather something" over a
 * bag full of berries). static/land.js townSpawn and hotbar, read as text beside static/land-recipes.json:
 *   1. the landing's view holds a townsperson: from townSpawn's place and yaw, one of the quests' npcs stands within
 *      8 m and within 35° of straight ahead, and none stands within a body's width of the landing itself;
 *   2. the empty bar names the bag: with things in the bag that cannot be placed, the bar's text is land.bagHeld with
 *      the count, not "gather something"; signed out it still says to sign in;
 *   3. land.bagHeld is in every one of the 17 languages with the count in it, and the languages that bend a noun by
 *      its number (cs, pl, ru, ar) carry their plural forms;
 *   4. one line says the next thing to do (goalLine, over the bar, refreshed with it): signed out — sign in; no work —
 *      talk to the elder (Q); work taken — the work; done — hand it in; and the plot card's price says how NADO is come
 *      by; the four strings in all 17 languages with their placeholders;
 *   5. the town comes with the first frame: start() asks for the hall's plot and its eight neighbours FIRST — before
 *      the rules load and the renderer is made — each fetch on its own (not awaited), at high priority.
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
const hb0 = land.indexOf("function hotbar()"), hb = land.slice(hb0, land.indexOf("\nfunction ", hb0 + 1));   // the whole function (a fixed 1200 chars missed the empty bar once the gadget keys' branch stood above it, #196)
ok(/const held = net\.me && RULES \? Object\.values\(inv\.items \|\| \{\}\)\.filter\(\(n\) => n > 0\)\.length : 0;/.test(hb)
   && /held \? T\("bagHeld", "[^"]*\{n\}[^"]*", \{ n: held \}\) : T\("emptyHands"/.test(hb) && /!net\.me \? T\("signInGather"/.test(hb),
   "with unplaceable things in the bag the empty bar says land.bagHeld with the count; signed out, sign in; empty, gather");

// 3. seventeen languages
const langs = Object.keys(I);
ok(langs.length === 17 && langs.every((l) => typeof I[l]["land.bagHeld"] === "string" && I[l]["land.bagHeld"].includes("{n}")), `land.bagHeld is in all ${langs.length} languages with the count`);
const forms = (l) => (/\{n\|([^}]*)\}/.exec(I[l]["land.bagHeld"] || "") || ["", ""])[1].split("|").map((f) => f.split(":")[0]);
ok(["cs", "pl", "ru"].every((l) => ["one", "few", "many", "other"].every((f) => forms(l).includes(f))) && ["zero", "one", "two", "few", "many", "other"].every((f) => forms("ar").includes(f)),
   "cs, pl and ru carry one/few/many/other, ar all six forms");

// 4. the first objective and the NADO sentence
const gl = land.slice(land.indexOf("function goalLine()"), land.indexOf("function hotbar()"));
ok(gl.length > 100 && /if \(!net\.me\) text = T\("signInBuild2"/.test(gl) && /q\.ready \? T\("goalReadyAt", "[^"]*\{who\}[^"]*\{q\}[^"]*", \{ who: questEnd\(q\), q: questText\(q\) \}\) : T\("goalQuest", "[^"]*\{q\}[^"]*", \{ q: questText\(q\) \}\)/.test(gl)
   && /n\.role === "elder"/.test(gl) && /T\("goalTalk", "[^"]*\{who\}[^"]*", \{ who:/.test(gl) && /^function hotbar\(\) \{\n  goalLine\(\);/m.test(land),
   "goalLine says sign in / talk to the elder / the work / hand it in, and runs with every hotbar refresh");
ok(/id="goal"/.test(readFileSync(join(ROOT, "static", "land.html"), "utf8")), "the page has the goal line over the bar");
ok(/t\.sale\) html = `[^`]*T\("nadoHow", "[^"]*dex\.nadochain\.com[^"]*"\)/.test(land), "the for-sale plot card says how NADO is come by");
const need = { "land.goalTalk": "{who}", "land.goalQuest": "{q}", "land.goalReadyAt": "{who}", "land.qReadyAt": "{who}", "land.nadoHow": "dex.nadochain.com" };
// A QUEST IS HANDED IN WHERE IT ENDS (playtest 2026-11-15: a parcel for Ida read "Done — hand it in … (Q at the one who
// gave it)", sending the player back to Maren): the goal line and the quest log name the addressee for a delivery
// (q.to), the giver otherwise — as the world server's turn-in checks (q.get("to") or q["giver"])
{
  const qe = land.slice(land.indexOf("function questEnd(q)"), land.indexOf("function goalLine()"));
  ok(/\.find\(\(x\) => x\.id === \(q\.to \|\| q\.giver\)\)/.test(qe) && /T\("qReadyAt", "Done — hand it in to \{who\}", \{ who: questEnd\(q\) \}\)/.test(land)
     && /\(q\.get\("to"\) or q\["giver"\]\) != nid/.test(readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8")),
     "a ready quest names who takes it — the addressee for a delivery, else the giver — in the goal line and the quest log, as the world server ends it");
  const RQ = R.quests.npcs;
  const qeFn = new Function("RULES", "roleName", qe + "\nreturn questEnd;")({ quests: { npcs: RQ } }, (r) => r);
  const ida = RQ.find((n) => /Ida/.test(n.name)), maren = RQ.find((n) => /Maren/.test(n.name));
  ok(qeFn({ kind: "deliver", giver: maren.id, to: ida.id }).startsWith("Ida") && qeFn({ kind: "bring", giver: maren.id }).startsWith("Maren"),
     `…a parcel from Maren for Ida is handed to ${qeFn({ kind: "deliver", giver: maren.id, to: ida.id })}; Maren's own errand to ${qeFn({ kind: "bring", giver: maren.id })}`);
}
ok(Object.entries(need).every(([k, ph]) => langs.every((l) => typeof I[l][k] === "string" && I[l][k].includes(ph))), "goalTalk/goalQuest/goalReadyAt/qReadyAt/nadoHow are in all 17 languages with their placeholders");

// 5. the town with the first frame
const st = land.slice(land.indexOf("async function start()"), land.indexOf("async function start()") + 1500);
const iRules = st.indexOf("RULES = await"), iPre = st.indexOf("prefetchTown();"), iRend = st.indexOf("new THREE.WebGPURenderer");
ok(iRules >= 0 && iPre >= 0 && iPre < iRules && iRend > iRules, "start() prefetches the town's plots before the rules load and the renderer");
ok(/fetch\("\/land\/api\/plot\?plot=" \+ plot, \{ cache: "no-store", credentials: "same-origin", priority: "high" \}\)/.test(land), "…at high fetch priority, ahead of the page's own downloads");
const pf = land.slice(land.indexOf("function prefetchTown()"), land.indexOf("async function resync("));
ok(/for \(let dr = -1; dr <= 1; dr\+\+\) for \(let dc = -1; dc <= 1; dc\+\+\) resync\(Wd\.plotId\(q\.face, q\.prow \+ dr, q\.pcol \+ dc\)\);/.test(pf) && !/await/.test(pf),
   "…the hall's plot and its eight neighbours, each fetch on its own, none awaited");


// THE TOWNSPEOPLE LOOK LIKE TOWNSPEOPLE (operator 2026-11-12, "why is their hair green and blue"): every townsperson's
// hair is one of the natural colours (the palette's first six: dark to grey) and each wears linen — a shirt and trousers
{
  const natural = 6, npcs = R.quests.npcs;
  ok(npcs.every((n) => n.look && Number.isInteger(n.look.hair) && n.look.hair < natural), `every townsperson's hair is a natural colour (${npcs.map((n) => `${n.id}:${n.look.hair}`).join(", ")})`);
  ok(npcs.every((n) => n.look.worn && n.look.worn.body === "linen_shirt" && n.look.worn.legs === "linen_trousers"), "…and each wears a linen shirt and linen trousers");
}

// A GATHERING JOB SAYS WHAT YOU HOLD OF IT (playtest 2026-11-15: carrying 2 stones, "Bring 6 × Stone" said nothing of
// them): the page's questText, run with 2 stones in the bag and with 9
{
  const a = land.indexOf("function questText(q) {"), b = land.indexOf("\n}\n", a);
  const mk = (n) => new Function("inv", "gatheredFrom", "T", "nameOf", "RULES", "animalName", "roleName", land.slice(a, b + 2) + "\nreturn questText;")(
    { items: { stone: n } }, () => "Loose stone", (k, fb, v) => fb.replace(/\{(\w+)\}/g, (_, x) => v[x]), (x) => x === "stone" ? "Stone" : x, R, (x) => x, (x) => x);
  const q = { kind: "bring", item: "stone", n: 6 };
  ok(mk(2)(q).endsWith("(2/6)") && mk(9)(q).endsWith("(6/6)") && mk(0)(q).endsWith("(0/6)"), `a gathering job counts what the bag holds: "${mk(2)(q)}", and never past the job: "${mk(9)(q)}"`);
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
