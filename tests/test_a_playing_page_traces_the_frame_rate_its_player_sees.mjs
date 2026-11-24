/*
 * test_a_playing_page_traces_the_frame_rate_its_player_sees.mjs — "smooth user experience" (the operator's goal): the
 * server renders in software, so its frame times say nothing of a player's GPU and every claim about smoothness was a
 * guess (2026-11-23). Once a minute a playing page traces the frame rate its player sees (land.js perfSample):
 *   1. the frame loop samples every frame;
 *   2. a minute of frames at 60 a second traces fps 60, its 95th-percentile frame and its worst, once, with the renderer,
 *      the view preset, the resolution scale and the screen;
 *   3. a gap over a second (a hidden tab) is no frame: it does not drag the rate down;
 *   4. the event fits the server's trace line (land_server.py trace_append: under 2,000 bytes, any kind);
 *   5. WHERE A LONG FRAME WENT (2026-11-24: minutes at a p95 of 300 ms on a GPU that drew Ultra at 90 fps the hour
 *      before, and nothing said why): a frame over 100 ms adds what ran since the one before, part by part, and the
 *      rest no part holds; the minute's trace carries the count and the top parts; every part the profiler names is
 *      timed with the profiler closed, the socket's messages and the titles' refresh among them;
 *   6. each step the graphics governor takes is traced (gov, from and to).
 * Run: node tests/test_a_playing_page_traces_the_frame_rate_its_player_sees.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), server = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
ok(/function frame\(now\) \{\n  if \(shotTick\(now\)\) return;\n  perfSample\(now\);/.test(page), "the frame loop samples every drawn frame");
// 2-3: the page's own code, run against a minute of frames
const src = page.slice(page.indexOf("const PERF = {"), page.indexOf("const tracePose = (p) =>"));
const traced = [];
const run = new Function("trace", "SET", "innerWidth", "innerHeight", "devicePixelRatio", src + "\nreturn [perfSample, PERF];");
const [perfSample, PERF] = run((k, d) => { const e = { t: 0, k, ...d }; traced.push(e); return e; }, { view: 6, res: 100 }, 1920, 1080, 1);
let t = 1000;
for (let i = 0; i < 1800; i++) { perfSample(t); t += 1000 / 60 + (i % 10 === 0 ? 8 : 0); }   // 60 a second, every tenth frame 8 ms late
t += 5000;                                                                                     // the tab hidden for 5 s
for (let i = 0; i < 1900 && traced.length < 1; i++) { perfSample(t); t += 1000 / 60; }
const e = traced[0];
ok(traced.length === 1 && e.k === "perf" && Math.abs(e.fps - 57.2) < 1.5 && e.p95 >= 16.6 && e.p95 <= 25 && Math.abs(e.worst - 24.7) < 0.2,
  `a minute of frames traces its rate once: ${JSON.stringify(e)}`);
ok(e && e.worst < 1000, "a hidden tab's gap is no frame (the worst frame is the late one, not the 5 s gap)");
ok(e && e.view === 6 && e.res === 100 && Array.isArray(e.px) && "gpu" in e, "…with the view preset, the resolution scale, the screen and the renderer");
// 4
ok(e && JSON.stringify(e).length < 2000 && /if len\(line\) > 2000:/.test(server) && /elif t == "trace":/.test(server), `the event fits the server's trace line (${e && JSON.stringify(e).length} bytes of 2,000)`);
// 5
{
  traced.length = 0;
  PERF.at = 0; PERF.last = 0; PERF.dts = [];                      // a fresh minute
  let t = 1e6; perfSample(t);
  for (let i = 0; i < 3700 && !traced.length; i++) {
    const long = i % 100 === 50;                                   // one frame in a hundred takes 250 ms (one in ~1.9 s: ~32 a minute)
    PERF.cur = long ? { render: 40, mesh: 150, step: 2 } : { render: 8, step: 1 };
    t += long ? 250 : 1000 / 60; perfSample(t);
  }
  const p = traced[0];
  ok(p && p.long >= 30 && p.long <= 34, `the minute's trace counts its frames over 100 ms (${p && p.long})`);
  ok(p && p.in && Object.keys(p.in)[0] === "mesh" && Math.abs(p.in.mesh / p.long - 150) < 1 && Math.abs(p.in.rest / p.long - 58) < 1 && Math.abs(p.in.render / p.long - 40) < 1,
    `…and where their time went, part by part, the most first, with the rest no part holds: ${JSON.stringify(p && p.in)}`);
  ok(p && !("step" in p.in && p.in.step > p.long * 2 + 1), "…counting only the long frames' parts, not every frame's");
  ok(p && JSON.stringify(p).length < 2000, "…and it still fits the trace line");
}
const ptSrc = page.slice(page.indexOf("function pt(label, fn) {"), page.indexOf("function profFrame("));
ok(/^function pt\(label, fn\) \{\n  const t0 = performance\.now\(\), r = fn\(\), ms = performance\.now\(\) - t0;\n  PERF\.cur\[label\]/.test(ptSrc),
  "every part the profiler names is timed with the profiler closed (pt always adds to PERF.cur)");
ok(page.includes('ws.onmessage = (ev) => pt("ws", () => wsIn(ev));') && page.includes('setInterval(() => pt("titles", refreshTitles), 30000);'),
  "…the socket's messages and the titles' refresh among them");
// 6
ok(/if \(to === at\) return;\n  trace\("gov", \{ from: LADDER\[at\], to: LADDER\[to\]/.test(page), "each step the graphics governor takes is traced");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
