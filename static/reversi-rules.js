// reversi-rules.js — pure rules + a deterministic, beatable bot for the free Daily Challenge (shared by
// reversi.js and tests/reversi_daily_verify.mjs via board-daily.js). You are player 1 (black), the seeded
// bot is player 2 (white). Board is 8x8; a move is a cell 0..63. The bot is GREEDY (grabs the most flips,
// loves corners) with a seeded tie-break — a well-known weak strategy, so skilled positional play beats it,
// and your final disc MARGIN feeds the score, so this daily genuinely differentiates.
import { prng } from "./board-daily.js";

export const SLUG = "reversi", MOVE_BITS = 6, MAX_MOVES = 60;
const NB = 8, DIRS = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]];

export function start() {
  const b = Array(64).fill(0);
  b[27] = 2; b[28] = 1; b[35] = 1; b[36] = 2;   // standard opening (d4/e5 black, d5/e4 white)
  return b;
}
// flips(b, cell, p): the list of opponent cells a play at `cell` by `p` would flip (empty if illegal).
function flips(b, cell, p) {
  if (b[cell]) return [];
  const r0 = Math.floor(cell / NB), c0 = cell % NB, opp = 3 - p, out = [];
  for (const [dr, dc] of DIRS) {
    const line = []; let r = r0 + dr, c = c0 + dc;
    while (r >= 0 && r < NB && c >= 0 && c < NB && b[r * NB + c] === opp) { line.push(r * NB + c); r += dr; c += dc; }
    if (line.length && r >= 0 && r < NB && c >= 0 && c < NB && b[r * NB + c] === p) out.push(...line);
  }
  return out;
}
export function legal(b, p) { const o = []; for (let i = 0; i < 64; i++) if (flips(b, i, p).length) o.push(i); return o; }
export function apply(b, cell, p) { const n = b.slice(); const fl = flips(b, cell, p); n[cell] = p; for (const f of fl) n[f] = p; return n; }
export const over = (b) => b.every((x) => x) || (!legal(b, 1).length && !legal(b, 2).length);
export function winner(b) { let a = 0, c = 0; for (const x of b) { if (x === 1) a++; else if (x === 2) c++; } return a > c ? 1 : c > a ? 2 : 0; }
export function margin(b) { let a = 0, c = 0; for (const x of b) { if (x === 1) a++; else if (x === 2) c++; } return a - c; }

const CORNERS = new Set([0, 7, 56, 63]);
export function bot(b, seed, ply) {
  const moves = legal(b, 2); if (!moves.length) return -1;
  const r = prng(seed + ":rv:" + ply);
  let best = -1, bestScore = -1e9;
  for (const m of moves) {
    // greedy: maximize flips, with a big corner bonus (weak but human-beatable) + tiny seeded jitter
    const s = flips(b, m, 2).length + (CORNERS.has(m) ? 10 : 0) + r() * 0.5;
    if (s > bestScore) { bestScore = s; best = m; }
  }
  return best;
}

// view(state, legal): the 8x8 grid; a cell's move is its own index.
export const COLS_VIEW = 8;
export function view(b, legalMoves) {
  const ok = new Set(legalMoves || []);
  return { cols: 8, cells: b.map((v, i) => ({ v, mv: ok.has(i) ? i : null })) };
}
