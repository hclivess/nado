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
 *   5. a source no hand can pick (needs a tool) or that is not the planet's litter is never pointed to;
 *   6. ONE region request brings the edits of the plots in the circle first; a bush picked (an edit) or under a piece is
 *      passed over;
 *   7. it waits for the plots' titles, and starts again when they change;
 *   8. the region request failing, it still runs and ends.
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
const a0 = page.indexOf("const SOURCE_R = "), b0 = page.indexOf("/** Who a quest is handed in to:");
const POINTS = [["cpN", "N"], ["cpNE", "NE"], ["cpE", "E"], ["cpSE", "SE"], ["cpS", "S"], ["cpSW", "SW"], ["cpW", "W"], ["cpNW", "NW"]];
const key = (f, u, v, h) => f + ":" + u + ":" + v + ":" + h;
// the page's sourceHint with the page's helpers stood in for: the world server's region answer (`region`, or a failing
// fetch), applyPlot writing a plot's edits into the edits map as the page does, the pieces a plot holds (pieceIn)
const make = (allow, { region = {}, fail = false, pieceIn = () => false, asked = [], at = { face: 0, u: 55047.5, v: 79996.5 } } = {}) => {
  const edits = new Map(), plotsApplied = new Set();
  const fetch = (url) => { asked.push(url); return fail ? Promise.reject(new Error("offline")) : Promise.resolve({ json: () => ({ plots: region }) }); };
  const applyPlot = (p, list) => { plotsApplied.add(p); const q = Wd.plotCoords(p); for (const [x, z, y, bl] of list) edits.set(key(q.face, q.u0 + x, q.v0 + z, y), bl); };
  const blockAt = (f, u, v, h) => { const e = edits.get(key(f, u, v, h)); return e !== undefined ? e : Wd.terrainBlock(f, u, v, h, (ff, uu, vv) => Wd.column(ff, uu, vv)); };
  return new Function("RULES", "Wd", "P", "W", "mayBuild", "inv", "questText", "T", "POINTS", "colAt", "edits", "key", "pieceIn", "plotsApplied", "fetch", "applyPlot", "setPlotBoxes", "blockAt",
    "let titlesVer = 0, titlesSig = \"\";\n" + page.slice(a0, b0) + "\ntitlesVer = 1;\nreturn { sourceHint, sourceBlocks, SOURCE_R, SOURCE_STEP };")(   // (the titles' version is declared at the top of the page)
    RULES, Wd, at, Wd.W ?? (1 << 17), allow, { quests: [{ kind: "bring", item: "berries", n: 6 }] },
    () => "Bring 6 × Berries", (k, fb, v) => fb.replace(/\{(\w+)\}/g, (_, x) => v[x]), POINTS, (f, u, v) => Wd.column(f, u, v), edits, key, pieceIn, plotsApplied, fetch, applyPlot, () => {}, blockAt);
};
const settle = () => new Promise((r) => setTimeout(r, 0));
const run = async (allow, opt) => { const S = make(allow, opt); const first = S.sourceHint("berries"); await settle(); let h = ""; for (let i = 0; i < 400 && !h; i++) h = S.sourceHint("berries"); return [h, S, first]; };
// the planet's own berry bushes around the landing, EVERY cell within 160 m, nearest first (the reference once sampled
// 2 m circles as the first search did, and agreed with it in missing the bush 3 m away)
const near = [];
for (let du = -160; du <= 160; du++) for (let dv = -160; dv <= 160; dv++) {
  const u = 55047 + du, v = 79996 + dv;
  const c = Wd.column(0, u, v);
  if (Wd.litterAt(0, u, v, c) === Wd.B.berrybush && Wd.terrainBlock(0, u, v, c.top + 1, (f, uu, vv) => Wd.column(f, uu, vv)) === Wd.B.berrybush) near.push([Math.round(Math.hypot(u + 0.5 - 55047.5, v + 0.5 - 79996.5)), Wd.plotOf(0, u, v), u, v, Math.hypot(u + 0.5 - 55047.5, v + 0.5 - 79996.5)]);
}
near.sort((x, y) => x[4] - y[4]);
const [h1, S, first] = await run(() => true);
ok(first === "" && near.length && h1.includes(`the nearest you may pick: ${near[0][0]} m`) && /m (N|NE|E|SE|S|SW|W|NW)$/.test(h1), `1. every plot open (nothing named before the region's edits are in): "${h1}" (the planet's nearest bush is ${near[0] && near[0][0]} m away)`);
{ // standing on a bush's own metre: "0 m NE" read as a riddle (playtest 2026-11-15, the stone errand) — it is right here
  const [h9] = await run(() => true, { at: { face: 0, u: near[0][2] + 0.5, v: near[0][3] + 0.5 } });
  ok(/there is one right here$/.test(h9) && !/ 0 m /.test(h9), `1b. standing on one, the line says it is right here, not "0 m" and a direction: "${h9}"`);
}
ok(S.sourceBlocks("berries").length === 1 && S.sourceBlocks("berries")[0] === Wd.B.berrybush, "…its source is the berry bush, the planet's litter");
const closed = new Set([near[0][1]]);                     // (the nearest bush's plot; the next open bush is farther)
const [h2] = await run((p) => !closed.has(p));
const d2 = Number((h2.match(/pick: (\d+) m/) || [])[1]);
ok(d2 > near[0][0], `2. the nearest bush's plot closed: it walks on to an open one, farther (${d2} m): "${h2}"`);
const [h3] = await run(() => false);
ok(/none you may pick within 160 m — look in the wilderness/.test(h3), `3. nothing open within reach: "${h3}"`);
ok(/for \(let n = 0; n < SOURCE_STEP && !s\.done && !s\.found; n\+\+\)/.test(page) && /const SOURCE_R = 160, SOURCE_STEP = 1500, SOURCE_MOVE = 12;/.test(page)
   && /if \(now - \(goalTick \|\| 0\) > 500 && \(inv\.quests \|\| \[\]\)\.some\(\(q\) => q\.kind === "bring" && !q\.ready\)\) \{ goalTick = now; goalLine\(\); \}/.test(page)
   && /if \(!q\.ready && q\.kind === "bring"\) \{ const h = sourceHint\(q\.item\); if \(h\) \{ g\.textContent = h; return; \} \}/.test(page),
  "4. it searches a slice a call, and the goal line asks for it twice a second while a bring-job is open");
ok(S.sourceBlocks("iron").length === 0 && S.sourceBlocks("nothing").length === 0, "5. no hint for what hands cannot pick from the planet's litter");
// 6. a bush that is no longer there is never pointed to: picked (its plot's edits, from the region answer), or under a piece
{
  const [, plot0, u, v] = near[0], h = Wd.column(0, u, v).top + 1, q = Wd.plotCoords(plot0);
  const asked = [];
  const [picked] = await run(() => true, { region: { [plot0]: { edits: [[u - q.u0, v - q.v0, h, Wd.B.air]], boxes: [] } }, asked });
  const [covered] = await run(() => true, { pieceIn: ([pu, pv]) => pu === u && pv === v });
  const d0 = near[0][0];
  ok(asked.length === 1 && /\/land\/api\/region\?face=0&u0=\d+&v0=\d+&u1=\d+&v1=\d+/.test(asked[0]) && !picked.includes(`pick: ${d0} m `) && /pick: \d+ m/.test(picked) && !covered.includes(`pick: ${d0} m `) && /pick: \d+ m/.test(covered),
    `6. ONE region request for the circle; the nearest bush picked (its plot's edits, from that answer) or under a laid path is passed over: "${picked}" / "${covered}"`);
}
// 7. not before the titles are in (until then every plot reads as open land) — and again when they change
ok(/if \(!titlesVer\) return "";/.test(page.slice(a0, b0)) && /const job = item \+ "@" \+ P\.face \+ "#" \+ titlesVer \+ "x" \+ \(\(inv\.items \|\| \{\}\)\[item\] \|\| 0\);/.test(page)
   && /if \(sig !== titlesSig\) \{ titlesSig = sig; titlesVer\+\+; \}/.test(page) && !/\n    titlesVer\+\+;/.test(page),
  "7. it waits for the titles (a first scan took a plot for sale for open land) and starts again only when they CHANGE (a bump on every refresh restarted it for ever) — or when the player's own count of the item changes (the bush just emptied stayed named)");
// 8. the region request failing, the search still runs (on what the page holds) and ends
{
  const [h8] = await run(() => false, { fail: true });
  ok(/none you may pick within 160 m/.test(h8), `8. the region request fails: the search still ends — "${h8.slice(0, 80)}…"`);
}
// 9. every cell is searched, from the player's own: the named bush is the truly nearest by distance (not the first on a
// square ring, whose corners are √2 farther), and the next nearest when it is gone
ok(Math.abs(Number((h1.match(/pick: (\d+) m/) || [])[1]) - near[0][0]) <= 0 && near[0][4] < 4,
  `9. it names the bush ${near[0][0]} m away — the nearest of all ${near.length} within 160 m (the circle sampler missed it and named 8 m)`);
// 10. a "bush" under a tree's crown (the crown wins the cell) is never named
{
  let under = null;
  for (let du = -40; du <= 40 && !under; du++) for (let dv = -40; dv <= 40 && !under; dv++) {
    const u = 55037 + du, v = 79916 + dv, c = Wd.column(0, u, v);
    if (Wd.litterAt(0, u, v, c) === Wd.B.berrybush && Wd.terrainBlock(0, u, v, c.top + 1, (f, uu, vv) => Wd.column(f, uu, vv)) !== Wd.B.berrybush) under = [u, v];
  }
  const src = page.slice(a0, b0);
  ok(under && /if \(blockAt\(P\.face, u, v, h\) === lb && !pieceIn\(\[u, v, h\]\)\)/.test(src),
    `10. a bush the planet grows under a tree's crown (one at ${under}) is judged by what stands in the cell — never named`);
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
