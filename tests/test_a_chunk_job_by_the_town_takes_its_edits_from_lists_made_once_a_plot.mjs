/*
 * test_a_chunk_job_by_the_town_takes_its_edits_from_lists_made_once_a_plot.mjs — "smooth user experience" (2026-11-24):
 * every chunk job carried the edits of the nine plots around it, each key built afresh — by the town hall ~5,000 a job,
 * ~8 ms each on this host, for every chunk of every column, and a profiled flight measured 100-500 ms ticks of
 * updateChunks. land.js editsFor now joins lists made once a plot (plotList):
 *   1. the list is exactly the one built afresh (the same keys and blocks), for a chunk by the hall;
 *   2. asked again it builds nothing new — at least five times faster than building afresh;
 *   3. a plot's list is dropped wherever its edits change: putCell, dropCell, applyPlot, the first hello.
 * Run: node tests/test_a_chunk_job_by_the_town_takes_its_edits_from_lists_made_once_a_plot.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const src = page.slice(page.indexOf("function editsFor("), page.indexOf("function request(k) {"));
const plotEdit = new Map(), plotList = new Map(), key = (f, u, v, h) => f + ":" + u + ":" + v + ":" + h;
const editsFor = new Function("Wd", "plotEdit", "plotList", "key", "CHUNK", "PLOT", src + "\nreturn editsFor;")(Wd, plotEdit, plotList, key, Wd.CHUNK, Wd.PLOT);
const hall = Wd.plotOf(0, 55040, 80000), q = Wd.plotCoords(hall);
for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
  const pe = new Map(); for (let i = 0; i < 600; i++) pe.set((i % 16) + ":" + ((i >> 4) % 16) + ":" + (100 + (i >> 8)), 1 + (i % 7));
  plotEdit.set(Wd.plotId(0, q.prow + dr, q.pcol + dc), pe);
}
const cu = q.u0 / Wd.CHUNK, cv = q.v0 / Wd.CHUNK;
// 1. against the list built afresh, the way the page built it before
const fresh = () => {
  const out = [];
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    const plot = Wd.plotId(0, q.prow + dr, q.pcol + dc), pe = plotEdit.get(plot), pq = Wd.plotCoords(plot);
    if (pe) for (const [lk, b] of pe) { const [x, z, y] = lk.split(":").map(Number); out.push([key(0, pq.u0 + x, pq.v0 + z, y), b]); }
  }
  return out;
};
const sig = (l) => l.map((e) => e.join("=")).sort().join(" ");
const a = editsFor(0, cu, cv);
ok(a.length === 5400 && sig(a) === sig(fresh()), `a chunk by the hall gets the same ${a.length} edits as built afresh`);
// 2
const time = (fn, n = 40) => { const t = performance.now(); for (let i = 0; i < n; i++) fn(); return (performance.now() - t) / n; };
time(() => editsFor(0, cu, cv), 5); time(fresh, 5);
const kept = time(() => editsFor(0, cu, cv)), afresh = time(fresh);
ok(plotList.size === 9 && kept * 5 < afresh, `asked again it builds nothing new: ${kept.toFixed(2)} ms a job against ${afresh.toFixed(2)} ms afresh`);
const b = editsFor(0, cu, cv); b.push(["x", 1]);
ok(editsFor(0, cu, cv).length === 5400, "…and a job's list is its own (one job's changes reach no other)");
// 3
const body = (name) => { const i = page.indexOf("function " + name + "("); return page.slice(i, page.indexOf("\n}\n", i)); };
ok(/plotList\.delete\(plot\)/.test(body("putCell")) && /plotList\.delete\(plot\)/.test(body("dropCell")) && /plotList\.delete\(plot\)/.test(body("applyPlot")),
  "a plot's list is dropped when its edits change: putCell, dropCell, applyPlot");
ok(/plotEdit\.clear\(\); plotList\.clear\(\);/.test(page), "…and on the first hello, with the cache it came from");
ok(!/plotEdit\.(set|delete|clear)\(|pe\.(set|delete)\(/.test(page.replace(/function (putCell|dropCell|applyPlot)\([\s\S]*?\n\}\n/g, "").replace(/plotEdit\.clear\(\); plotList\.clear\(\);/, "")),
  "…and nothing else changes a plot's edits behind it");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
