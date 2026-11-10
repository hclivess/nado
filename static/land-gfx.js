// land-gfx.js — GRAPHICS PRESETS AND THE BENCHMARK'S DECISION (#166, operator 2026-11-10: "performance benchmark that
// sets graphical settings. also make graphical settings more configurable"). Pure: no page, no renderer — the page
// (land.js) applies a preset, measures its frames and asks here which preset this device holds; a test asks the same
// with frame times it makes up.

/** What each preset sets (land.js SET keys): render resolution %, shadows 0-3, view distance in chunks, grass, effects. */
export const GFX_PRESETS = {
  low: { res: 60, shadows: 0, view: 3, grass: 0, effects: 0 },
  medium: { res: 80, shadows: 1, view: 4, grass: 1, effects: 0 },
  high: { res: 100, shadows: 2, view: 6, grass: 1, effects: 1 },
  ultra: { res: 100, shadows: 3, view: 8, grass: 1, effects: 1 },
};
/** Tried from the top: the first that holds the target is kept, so a fast device measures one preset, not four. */
export const BENCH_ORDER = ["ultra", "high", "medium", "low"];
/** Frames a second a preset must hold: a phone 30, anything else 60. */
export const benchTarget = (phone) => (phone ? 30 : 60);

/** p50 and p95 of frame intervals (ms), and the frames a second the median gives. Empty -> null. */
export function frameStats(ms) {
  const s = (ms || []).filter((x) => Number.isFinite(x) && x > 0).sort((a, b) => a - b);
  if (!s.length) return null;
  const q = (f) => s[Math.min(s.length - 1, Math.floor(f * s.length))];
  const p50 = q(0.5), p95 = q(0.95);
  return { p50, p95, fps: 1000 / p50, n: s.length };
}

/** A preset holds the target when its median frame is within the frame budget — with 15% for a screen's own refresh (a
 *  60 Hz screen paces a 60 fps target at exactly its budget) — and its slow frames (p95) within 1.8 budgets: a few
 *  hitches are allowed, a stutter every few frames is not. */
export function holds(stats, target) {
  if (!stats || stats.n < 5) return false;
  const budget = 1000 / target;
  return stats.p50 <= budget * 1.15 && stats.p95 <= budget * 1.8;
}

/** The preset to keep: the first in BENCH_ORDER whose measured frames hold the target; Low when none does (a device too
 *  slow for Low still plays best on it). `measured` maps a preset name to its frame intervals (ms). */
export function pickPreset(measured, target) {
  for (const name of BENCH_ORDER) if (measured[name] && holds(frameStats(measured[name]), target)) return name;
  return "low";
}

// ---- THE GOVERNOR (#166: "then an automatic governor while playing", after True Wind's GfxAuto): between frames it
// watches the frame intervals and moves one preset down when frames have been slow for downS seconds, one up when they
// have been fast for upS — slow and fast far enough apart (slowK, fastK) that it does not hunt between two. After a step
// it holds holdS seconds and judges it: a step down that did not make frames at least (1 - helpK) faster is taken back
// (the device is not slow for graphics — a busy main thread, a page in the background) and no step down is tried again
// for noDownS; a step up that came out slow is taken back and no step up is tried for noUpS.
export const GOV = { win: 30, slowK: 1.55, fastK: 0.93, downS: 3, upS: 12, holdS: 4, helpK: 0.9, noDownS: 60, noUpS: 120 };
/** The ladder the governor walks, lightest first. */
export const LADDER = BENCH_ORDER.slice().reverse();
const median = (a) => { const s = a.slice().sort((x, y) => x - y); return s[s.length >> 1]; };
export function governor(target) {
  return { budget: 1000 / target, ms: [], slowSince: null, fastSince: null, holdUntil: 0, tried: null, noDownUntil: 0, noUpUntil: 0 };
}
/** One frame: `dt` its interval (ms), `now` the time (ms), `at` the preset's index in LADDER. Returns the index to be at
 *  (the same one when nothing changes). */
export function govStep(g, dt, now, at) {
  // a stall says nothing of the graphics (a pause, a tab coming back): 5 s, not 1 — a 1 fps device is the one to help
  if (!(dt > 0) || dt > 5000) return at;
  g.ms.push(dt); if (g.ms.length > GOV.win) g.ms.shift();
  if (now < g.holdUntil || g.ms.length < 10) return at;
  const med = median(g.ms), step = (to, dir) => {
    g.tried = { dir, from: at, before: med }; g.holdUntil = now + GOV.holdS * 1000; g.ms = []; g.slowSince = g.fastSince = null;
    return to;
  };
  if (g.tried) {                                            // the hold is over: did the last step do what it was for?
    const t = g.tried; g.tried = null;
    if (t.dir < 0 && med > t.before * GOV.helpK) { g.noDownUntil = now + GOV.noDownS * 1000; g.ms = []; return t.from; }
    if (t.dir > 0 && med > g.budget * GOV.slowK) { g.noUpUntil = now + GOV.noUpS * 1000; g.ms = []; return t.from; }
  }
  if (med > g.budget * GOV.slowK) {
    g.fastSince = null; if (g.slowSince === null) g.slowSince = now;
    if (now - g.slowSince >= GOV.downS * 1000 && at > 0 && now >= g.noDownUntil) return step(at - 1, -1);
  } else if (med < g.budget * GOV.fastK) {
    g.slowSince = null; if (g.fastSince === null) g.fastSince = now;
    if (now - g.fastSince >= GOV.upS * 1000 && at < LADDER.length - 1 && now >= g.noUpUntil) return step(at + 1, 1);
  } else g.slowSince = g.fastSince = null;
  return at;
}
