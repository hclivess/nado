/*
 * stormhold-bot.js — a legal-move generator over the REAL engine, shared by the fuzz tests, the live
 * on-chain E2E oracle AND the in-browser practice mode (duelgame.js "vs computer"): given a replayed
 * state it produces one legal move for the current actor, mirroring what the UI would allow.
 */
import * as E from "./stormhold-engine.js";
const { CARDS, encMove, gainable } = E;
const isA = (id) => !!(CARDS[id].t & 1), isT = (id) => !!(CARDS[id].t & 2), isV = (id) => !!(CARDS[id].t & 4);
const SKIP = 4095;

// deterministic PRNG for the playout choices (NOT the game's shuffles — those use the engine's H chain)
export function prng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
const pick = (rnd, arr) => arr[Math.floor(rnd() * arr.length)];
const maskOf = (idxs) => idxs.reduce((m, i) => m + 2 ** i, 0);
function randSubset(rnd, n, max) {   // random subset of 0..n-1, size ≤ max
  const idxs = [];
  for (let i = 0; i < n; i++) if (rnd() < 0.4 && idxs.length < max) idxs.push(i);
  return idxs;
}
function chooseN(rnd, n, k) {        // k distinct indices of 0..n-1
  const all = Array.from({ length: n }, (_, i) => i);
  for (let i = all.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [all[i], all[j]] = [all[j], all[i]]; }
  return all.slice(0, k);
}

// generate ONE legal move for the current actor — the fuzzer's "player"
export function randomMove(st, rnd) {
  if (st.frames.length) {
    const f = st.frames[st.frames.length - 1], z = st.ps[f.p];
    const D = (payload) => ({ side: f.p + 1, enc: encMove(5, payload) });
    switch (f.t) {
      case "cel": return D(maskOf(randSubset(rnd, z.hand.length, z.hand.length)));
      case "chp": return D(maskOf(randSubset(rnd, z.hand.length, 4)));
      case "har": return D(Math.floor(rnd() * (z.disc.length + 1)));
      case "vas": case "lib": case "mon": case "moat": return D(rnd() < 0.5 ? 1 : 0);
      case "mil": return D(maskOf(chooseN(rnd, z.hand.length, z.hand.length - 3)));
      case "bur": return D(pick(rnd, z.hand.map((c, i) => [c, i]).filter(([c]) => isV(c)).map(([, i]) => i)));
      case "ban": return D(pick(rnd, f.cards.map((c, i) => [c, i]).filter(([c]) => isT(c) && c !== 0).map(([, i]) => i)));
      case "poa": return D(maskOf(chooseN(rnd, z.hand.length, f.n)));
      case "remT": return D(Math.floor(rnd() * z.hand.length));
      case "remG": { const g = gainable(st, f.max); return D(g.length ? pick(rnd, g) : SKIP); }
      case "thr": { const acts = z.hand.map((c, i) => [c, i]).filter(([c]) => isA(c)).map(([, i]) => i);
        return D(acts.length && rnd() < 0.8 ? pick(rnd, acts) : SKIP); }
      case "minT": { const ts = z.hand.map((c, i) => [c, i]).filter(([c]) => isT(c)).map(([, i]) => i);
        return D(ts.length && rnd() < 0.8 ? pick(rnd, ts) : SKIP); }
      case "minG": { const g = gainable(st, f.max, true); return D(g.length ? pick(rnd, g) : SKIP); }
      case "sen": { const n = f.cards.length;
        const d0 = Math.floor(rnd() * 3), d1 = n === 2 ? Math.floor(rnd() * 3) : 0;
        const swap = n === 2 && d0 === 0 && d1 === 0 && rnd() < 0.5 ? 1 : 0;
        return D(d0 + 3 * d1 + 9 * swap); }
      case "artG": { const g = gainable(st, 5); return D(g.length ? pick(rnd, g) : SKIP); }
      case "artT": return D(Math.floor(rnd() * z.hand.length));
      case "wsh": { const g = gainable(st, 4); return D(g.length ? pick(rnd, g) : SKIP); }
      default: throw new Error("fuzzer: unknown frame " + f.t);
    }
  }
  const p = st.turn, z = st.ps[p];
  const M = (op, payload) => ({ side: p + 1, enc: encMove(op, payload) });
  const acts = z.hand.map((c, i) => [c, i]).filter(([c]) => isA(c)).map(([, i]) => i);
  if (st.phase === 0 && st.actions > 0 && acts.length && rnd() < 0.75) return M(1, pick(rnd, acts));
  const ts = z.hand.map((c, i) => [c, i]).filter(([c]) => isT(c)).map(([, i]) => i);
  if (ts.length && rnd() < 0.85) return M(2, maskOf(ts));
  const afford = Object.keys(st.supply).map(Number).filter((id) => st.supply[id] > 0 && CARDS[id].c <= st.coins);
  if (st.buys > 0 && afford.length && rnd() < 0.9) {
    // buy-biased: prefer expensive cards so games actually end
    afford.sort((a, b) => CARDS[b].c - CARDS[a].c);
    return M(3, rnd() < 0.7 ? afford[0] : pick(rnd, afford));
  }
  return M(4, 0);
}

