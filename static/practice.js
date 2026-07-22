// practice.js — the shared PRACTICE-MODE scaffold: free single-player play that runs entirely in the
// browser and NEVER touches the chain (no wallet, no stakes, no txs). Games mount a self-contained
// "🎯 Practice" card built from these primitives, so the real staked game above is never modified:
//
//   - prand(seed) / randomSeed(slug): deterministic seeded RNG (practice-grade, NOT consensus)
//   - Practice(slug): play-money CHIPS bank + persisted run state + local best scores + W-L-D tally +
//     the shared header strip (chips balance, reset, "nothing on-chain" note) — all in localStorage
//
// i18n: every shared string lives under the sdk.* bundle so new games add ZERO translation keys for
// the common chrome. The distinction from real play is loud by design (see [[ux-is-priority]]): the
// strip always says these are play chips.
import { $ } from "./nadodapp.js?v=77a0d4df";

const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sdk." + k, d, v) : d;

// ---- seeded RNG (xmur3 string hash -> mulberry32) — deterministic across browsers, NOT for consensus
export function prand(seedStr) {
  let h = 1779033703 ^ String(seedStr).length;
  for (let i = 0; i < String(seedStr).length; i++) {
    h = Math.imul(h ^ String(seedStr).charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  let a = (h ^= h >>> 16) >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const randomSeed = (slug) => slug + "-rnd-" + Math.random().toString(36).slice(2, 10);

export const START_CHIPS = 1000;

export class Practice {
  constructor(slug) {
    this.slug = slug;
    this.LS = "nado_practice_" + slug;
  }
  _all() { try { return JSON.parse(localStorage.getItem(this.LS) || "{}"); } catch { return {}; } }
  _put(d) { try { localStorage.setItem(this.LS, JSON.stringify(d)); } catch {} }

  // ---- play-money chips (money-game practice) --------------------------------------------------------
  chips() { const d = this._all(); return d.chips == null ? START_CHIPS : d.chips; }
  setChips(n) { const d = this._all(); d.chips = Math.max(0, Math.round(n)); this._put(d); return d.chips; }
  addChips(delta) { return this.setChips(this.chips() + delta); }
  resetChips() { return this.setChips(START_CHIPS); }
  // canBet: loud client-side gate — a quiet failure reads as a bug
  canBet(n, notifyFn) {
    if (n > 0 && n <= this.chips()) return true;
    if (notifyFn) notifyFn(n <= 0 ? T("prBadBet", "Enter a practice bet first.")
      : T("prNoChips", "Not enough practice chips — reset them for free."));
    return false;
  }

  // ---- persisted run state (board games, solo runs) ---------------------------------------------------
  run() { return this._all().run || null; }
  saveRun(run) { const d = this._all(); d.run = run; this._put(d); }
  clearRun() { const d = this._all(); delete d.run; this._put(d); }

  // ---- local best scores -----------------------------------------------------------------------------
  best(key) { return (this._all().best || {})[key] || 0; }
  bump(key, score) {
    const d = this._all(); d.best = d.best || {};
    if ((d.best[key] || 0) >= score) return false;
    d.best[key] = score; this._put(d); return true;
  }
  // win/loss tally for vs-AI games
  tally(result) {   // "w" | "l" | "d"
    const d = this._all(); d.t = d.t || { w: 0, l: 0, d: 0 }; d.t[result]++; this._put(d); return d.t;
  }
  tallies() { return this._all().t || { w: 0, l: 0, d: 0 }; }

  // ---- the shared header strip -------------------------------------------------------------------------
  // strip($("pStrip"), {chips:true, tally:true, onReset}) — renders the loud "play chips / nothing
  // on-chain" banner + balance + reset. Call again to refresh.
  strip(el, opts) {
    if (!el) return;
    opts = opts || {};
    const bits = ['<span class="chip" style="border-color:var(--gold);color:var(--gold)">🎯 '
      + T("prBanner", "PRACTICE — free play, nothing on-chain") + "</span>"];
    if (opts.chips !== false) bits.push('<span class="chip">🪙 ' + this.chips() + " " + T("prChips", "play chips") + "</span>");
    if (opts.tally) { const t = this.tallies(); bits.push('<span class="chip">' + T("prTally", "W{w}–L{l}–D{d} vs computer", t) + "</span>"); }
    el.innerHTML = bits.join(" ");
    if (opts.chips !== false) {
      const b = document.createElement("button"); b.className = "ghost"; b.style.cssText = "padding:5px 10px;font-size:12px;margin-left:4px";
      b.textContent = T("prReset", "↺ Reset chips");
      b.onclick = () => { this.resetChips(); if (opts.onReset) opts.onReset(); this.strip(el, opts); };
      el.appendChild(b);
    }
  }
}
