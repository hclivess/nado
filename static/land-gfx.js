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
