/*
 * test_finished_chunks_are_applied_within_a_frame_budget_and_photo_mode_still_waits_for_them.mjs — #150 (operator
 * 2026-11-12: "the performance varies, there are severe staggers"; measured on the live page: "mesh 31.8 ms" and
 * "borders 358 ms" in single frames). static/land.js, read as source (the page's frame loop is not callable in node):
 *   1. a worker's finished result is QUEUED, not applied in its message handler — applied in the frame within
 *      MESH_BUDGET_MS, at least one a frame, so three chunks landing together are spread over frames;
 *   2. photo mode, which returns from the frame early while chunks are in flight, still applies the results it waits
 *      for (or it waited forever: inflight never emptied);
 *   3. the ownership outline is cached a plot at a time (kind, pieces, edits, width, edges drawn) and a rebuild only
 *      concatenates the kept parts — the 358 ms rebuild at every plot line crossed.
 * Run: node tests/test_finished_chunks_are_applied_within_a_frame_budget_and_photo_mode_still_waits_for_them.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
ok(page.includes('w.onmessage = (e) => { w.busy = false; finished.push(e.data); pump(); };'), "a worker's result is queued, not applied in its handler");
ok(/const finished = \[\], MESH_BUDGET_MS = \d+;/.test(page) && page.includes("while (finished.length && (n === 0 || performance.now() - t0 < MESH_BUDGET_MS)) { done(finished.shift()); n++; }"), "…applied within the frame's mesh budget, at least one a frame");
ok(page.includes('pt("mesh", applyFinished);'), "…from the frame loop");
const shot = page.slice(page.indexOf("function shotTick(now) {"), page.indexOf("function shotTick(now) {") + 400);
ok(shot.includes("applyFinished();") && shot.indexOf("applyFinished();") < shot.indexOf("if (queue.length || inflight.size"), "photo mode applies the results it waits for before judging what is in flight");
ok(page.includes("let part = borderCache.get(p);") && page.includes("if (!part || part.key !== key) {") && page.includes("for (const p of [...borderCache.keys()]) if (!keep.has(p)) borderCache.delete(p);"), "the ownership outline is cached a plot at a time and pruned to the plots around");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
