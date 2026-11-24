/*
 * test_the_graphics_governor_steps_down_when_slow_up_when_fast_and_takes_back_a_step_that_did_not_help.mjs — THE
 * GOVERNOR (#166: "an automatic governor while playing", operator 2026-11-10; static/land-gfx.js govStep), driven with
 * simulated frames — each preset given its own frame time, as a device would draw it:
 *   1. frames slow for 3 s move it one preset down — not sooner; frames on time move nothing;
 *   2. frames fast for 12 s move it one up — not sooner;
 *   3. a device slow at every preset, each step lighter helping, falls to Low and stays there;
 *   4. a step down that does not make frames faster is taken back, and no step down is tried again for a minute;
 *   5. a step up that comes out slow is taken back, and no step up is tried for two minutes (no hunting);
 *   6. a 1 fps device is governed too (a frame of a second is not a stall), a 6 s gap is ignored;
 *   7. the page walks this ladder only on a preset, on by default with an opt-out, and not in headless browsers;
 *   8. a futile step waits twice as long each time in a row (2026-11-24: a real player's trace held a High ↔ Medium step
 *      retried every minute for twenty, each one a stall of its own) — and still tries again, and a step that stands
 *      starts the count over.
 *
 * Run: node tests/test_the_graphics_governor_steps_down_when_slow_up_when_fast_and_takes_back_a_step_that_did_not_help.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const G = await import(join(ROOT, "static", "land-gfx.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };
const L = G.LADDER, at = (n) => L.indexOf(n);

/** Play `secs` seconds from preset `start`, each frame taking frameMs(presetName, t) ms; returns [{t, to}] changes and
 *  where it ended. */
function play(start, frameMs, secs, target = 60, t0 = 0, g = G.governor(target)) {
  let i = at(start), t = t0; const changes = [];
  while (t < t0 + secs * 1000) {
    const dt = frameMs(L[i], t);
    t += dt;
    const to = G.govStep(g, dt, t, i);
    if (to !== i) { changes.push({ t: Math.round(t), from: L[i], to: L[to] }); i = to; }
  }
  return { end: L[i], changes, g, t };
}

ok(L.join() === "low,medium,high,ultra", "the governor walks Low → Ultra");

// 1. slow
const cost = { low: 12, medium: 20, high: 40, ultra: 60 };            // a device that holds Medium, not High
let r = play("high", (p) => cost[p], 2.5);
ok(r.changes.length === 0, "2.5 s of slow frames move nothing yet");
r = play("high", (p) => cost[p], 8);
ok(r.changes[0] && r.changes[0].to === "medium" && r.changes[0].t >= 3000 && r.changes[0].t < 4500, `slow for 3 s, it steps down to Medium (at ${r.changes[0] && r.changes[0].t} ms)`);
ok(r.end === "medium", "…and Medium, on time, is kept");
r = play("medium", () => 17, 60);
ok(r.changes.length === 0, "a minute of frames on time (17 ms) moves nothing");

// 2. fast
r = play("low", (p) => cost[p], 11);
ok(r.changes.length === 0, "11 s of fast frames move nothing yet");
r = play("low", (p) => cost[p], 40);
ok(r.changes[0] && r.changes[0].to === "medium" && r.changes[0].t >= 12000, `fast for 12 s, it steps up to Medium (at ${r.changes[0] && r.changes[0].t} ms)`);
ok(r.end === "medium", "…and never up to High, which it cannot hold: " + JSON.stringify(r.changes));

// 3. slow everywhere
r = play("ultra", (p) => ({ ultra: 120, high: 90, medium: 60, low: 40 }[p]), 60);
ok(r.end === "low" && r.changes.map((c) => c.to).join() === "high,medium,low", "a device slow at every preset, each step lighter helping, falls step by step to Low: " + JSON.stringify(r.changes.map((c) => c.to)));

// 4. a step down that did not help
r = play("high", () => 45, 50);
ok(r.changes.length >= 2 && r.changes[0].to === "medium" && r.changes[1].to === "high", "a step down that left frames as slow is taken back: " + JSON.stringify(r.changes.slice(0, 2)));
ok(r.changes.length === 2, "…and for the next minute no step down is tried again");
r = play("high", () => 45, 90);
ok(r.changes.length === 4, "…after it, one is tried once more: " + JSON.stringify(r.changes.map((c) => c.to)));

// 5. a step up that came out slow
const tight = { low: 12, medium: 14, high: 40, ultra: 60 };
r = play("medium", (p) => tight[p], 130);
const ups = r.changes.filter((c) => c.to === "high");
ok(ups.length === 1, "a step up to High that came out slow is tried once in two minutes, not again and again: " + JSON.stringify(r.changes));
ok(r.end === "medium", "…and it ends back at Medium");

// 6. slow devices and stalls
r = play("medium", (p) => ({ low: 400, medium: 1200 }[p] || 2000), 60, 30);
ok(r.changes.some((c) => c.to === "low"), "a 1 fps device is governed too (a 1.2 s frame is slow, not a stall)");
const g = G.governor(60);
ok(G.govStep(g, 6000, 6000, 2) === 2 && g.ms.length === 0, "a 6 s gap (a pause, a tab coming back) is not counted");

// 8. futile steps back off
{
  const tries = (r) => r.changes.filter((c) => c.to === "medium").map((c) => c.t);
  r = play("high", () => 45, 600);
  const d = tries(r);
  ok(d.length >= 3 && d.length <= 5, `ten minutes slow for something else: ${d.length} tries down, not ten (at ${d.map((x) => Math.round(x / 1000))} s)`);
  const waits = d.slice(1).map((x, i) => x - d[i]);
  ok(waits.every((w, i) => i === 0 || w > waits[i - 1] * 1.7), `…each wait about twice the last: ${waits.map((w) => Math.round(w / 1000))} s`);
  r = play("high", () => 45, 3 * 3600);
  const late = tries(r), gaps = late.slice(1).map((x, i) => x - late[i]);
  ok(Math.max(...gaps) <= (G.GOV.noDownS * 2 ** G.GOV.futileMax + 30) * 1000 && late.length >= 12,
    `…up to ${G.GOV.noDownS * 2 ** G.GOV.futileMax / 60} min at most, and it keeps trying (${late.length} tries in three hours, longest wait ${Math.round(Math.max(...gaps) / 60000)} min)`);
  const g2 = G.governor(60); g2.futileDown = 3;
  let i = at("high"), t = 0;
  while (t < 20000) { const dt = i === at("high") ? 45 : 16; t += dt; i = G.govStep(g2, dt, t, i); }
  ok(L[i] === "medium" && g2.futileDown === 0, "a step down that helped starts the count over");
}

// 7. the page
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(page.includes("const at = LADDER.indexOf(gfxPreset());\n  if (at < 0) { gov = null; return; }"), "the page governs only a preset (a player's Custom mix is left alone)");
ok(/\bauto: 1[,} ]/.test(page.slice(page.indexOf("const SET_DEF ="), page.indexOf("const SET_DEF =") + 300)) && page.includes('sel("auto",'), "…on by default, with an opt-out in the panel");   // (SET_DEF gained keys after auto: the clouds, #183)
ok(page.includes("!/HeadlessChrome/.test(navigator.userAgent) || new URLSearchParams(location.search).has(\"gov\")"), "…not in a headless browser unless asked (?gov)");
ok(page.includes("govTick(now, gap);"), "…and decided in every frame, before it is drawn");

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
