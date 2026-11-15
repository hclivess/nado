/*
 * test_a_gathering_job_points_to_the_nearest_source_the_player_may_pick.mjs — playtest 2026-11-15, the agent's berry
 * errand from the town: the goal line said "found as Berry bush" and every bush within 84 m of the landing stood on
 * someone's plot ("not yours to gather here"), with nothing to say where one could be picked. land.js sourceHint, run
 * here on the planet itself (land-world.js) from the landing:
 *   1. with every plot open it finds the nearest berry bush the planet has there, and says its distance and compass point;
 *   2. with the nearest bushes' plots closed it walks on to the nearest bush on open land — farther, never a closed one;
 *   3. with nothing open within SOURCE_R it says so and sends the player to the wilderness;
 *   4. it searches a slice at a time (SOURCE_STEP points a call), and the goal line asks for it twice a second while a
 *      bring-job is open;
 *   5. a source no hand can pick (needs a tool) or that is not the planet's litter is never pointed to.
 * Run: node tests/test_a_gathering_job_points_to_the_nearest_source_the_player_may_pick.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf("const SOURCE_R = "), b = page.indexOf("/** Who a quest is handed in to:");
const POINTS = [["cpN", "N"], ["cpNE", "NE"], ["cpE", "E"], ["cpSE", "SE"], ["cpS", "S"], ["cpSW", "SW"], ["cpW", "W"], ["cpNW", "NW"]];
const key = (f, u, v, h) => f + ":" + u + ":" + v + ":" + h;
const make = (allow, edits = new Map(), pieceIn = () => false) => new Function("RULES", "Wd", "P", "W", "mayBuild", "inv", "questText", "T", "POINTS", "colAt", "edits", "key", "pieceIn",
  page.slice(a, b) + "\ntitlesVer = 1;\nreturn { sourceHint, sourceBlocks, SOURCE_R, SOURCE_STEP };")(
  RULES, Wd, { face: 0, u: 55047.5, v: 79996.5 }, Wd.W ?? (1 << 17), allow, { quests: [{ kind: "bring", item: "berries", n: 6 }] },
  () => "Bring 6 × Berries", (k, fb, v) => fb.replace(/\{(\w+)\}/g, (_, x) => v[x]), POINTS, (f, u, v) => Wd.column(f, u, v), edits, key, pieceIn);
const runWith = (allow, edits, pieceIn) => { const S = make(allow, edits, pieceIn); let h = ""; for (let i = 0; i < 400 && !h; i++) h = S.sourceHint("berries"); return h; };
const run = (allow) => { const S = make(allow); let h = ""; for (let i = 0; i < 400 && !h; i++) h = S.sourceHint("berries"); return [h, S]; };
// the planet's own nearest berry bush from the landing, found the slow way
const near = [];
for (let r = 2; r <= 160 && near.length < 1; r += 2) for (let t = 0; t < 2 * Math.PI && near.length < 1; t += 2 / r) {
  const u = Math.floor(55047.5 + r * Math.sin(t)), v = Math.floor(79996.5 + r * Math.cos(t));
  if (Wd.litterAt(0, u, v, Wd.column(0, u, v)) === Wd.B.berrybush) near.push([r, Wd.plotOf(0, u, v), u, v]);
}
const [h1, S] = run(() => true);
ok(near.length && h1.includes(`the nearest you may pick: ${near[0][0]} m`) && /m (N|NE|E|SE|S|SW|W|NW)$/.test(h1), `1. every plot open: "${h1}" (the planet's nearest bush is ${near[0] && near[0][0]} m away)`);
ok(S.sourceBlocks("berries").length === 1 && S.sourceBlocks("berries")[0] === Wd.B.berrybush, "…its source is the berry bush, the planet's litter");
const closed = new Set([near[0][1]]);
const [h2] = run((p) => !closed.has(p));
const d2 = Number((h2.match(/pick: (\d+) m/) || [])[1]);
ok(d2 > near[0][0], `2. the nearest bush's plot closed: it walks on to an open one, farther (${d2} m): "${h2}"`);
const [h3] = run(() => false);
ok(/none you may pick within 160 m — look in the wilderness/.test(h3), `3. nothing open within reach: "${h3}"`);
ok(/for \(let n = 0; n < SOURCE_STEP && !s\.done && !s\.found; n\+\+\)/.test(page) && /const SOURCE_R = 160, SOURCE_STEP = 600, SOURCE_MOVE = 12;/.test(page)
   && /if \(now - \(goalTick \|\| 0\) > 500 && \(inv\.quests \|\| \[\]\)\.some\(\(q\) => q\.kind === "bring" && !q\.ready\)\) \{ goalTick = now; goalLine\(\); \}/.test(page)
   && /if \(!q\.ready && q\.kind === "bring"\) \{ const h = sourceHint\(q\.item\); if \(h\) \{ g\.textContent = h; return; \} \}/.test(page),
  "4. it searches a slice a call, and the goal line asks for it twice a second while a bring-job is open");
ok(S.sourceBlocks("iron").length === 0 && S.sourceBlocks("nothing").length === 0, "5. no hint for what hands cannot pick from the planet's litter");
// 6. a bush that is no longer there is never pointed to: picked (an edit of air over it), or under a piece
{
  const [, , u, v] = near[0], h = Wd.column(0, u, v).top + 1;
  const picked = runWith(() => true, new Map([[key(0, u, v, h), Wd.B.air]]));
  const covered = runWith(() => true, new Map(), ([pu, pv]) => pu === u && pv === v);
  const d0 = near[0][0];
  ok(!picked.includes(`pick: ${d0} m `) && /pick: \d+ m/.test(picked) && !covered.includes(`pick: ${d0} m `) && /pick: \d+ m/.test(covered),
    `6. the nearest bush picked, or under a laid path, is passed over for the next: "${picked}" / "${covered}"`);
}
// 7. not before the titles are in (until then every plot reads as open land) — and again when they change
ok(/if \(!titlesVer\) return "";/.test(page.slice(a, b)) && /const job = item \+ "@" \+ P\.face \+ "#" \+ titlesVer;/.test(page) && /\n    titlesVer\+\+;  /.test(page),
  "7. it waits for the titles (a first scan took a plot for sale for open land) and starts again when they change");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
