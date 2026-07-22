// connect4-rules.js — pure rules + a deterministic, beatable bot for the free Daily Challenge (shared by
// connect4.js and tests/connect4_daily_verify.mjs via board-daily.js). You are player 1 (drop first), the
// seeded bot is player 2. Board is 7 columns x 6 rows; a move is a column 0..6. The bot takes a win, blocks
// a loss, avoids handing you a win, else plays center-biased with a seeded tie-break — solid but not perfect.
import { prng } from "./board-daily.js?v=ff35df1e";

export const SLUG = "connect4", MOVE_BITS = 3, MAX_MOVES = 42;
export const COLS = 7, ROWS = 6;

export const start = () => Array.from({ length: COLS }, () => []);        // state = 7 columns, each a stack (bottom-first) of 1/2
export const legal = (b) => { const o = []; for (let c = 0; c < COLS; c++) if (b[c].length < ROWS) o.push(c); return o; };
export function apply(b, c, p) { const n = b.map((col) => col.slice()); n[c].push(p); return n; }
const at = (b, c, r) => (c >= 0 && c < COLS && r >= 0 && r < b[c].length ? b[c][r] : 0);
export function winner(b) {
  for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) {
    const p = at(b, c, r); if (!p) continue;
    for (const [dc, dr] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      let k = 1; while (k < 4 && at(b, c + dc * k, r + dr * k) === p) k++;
      if (k === 4) return p;
    }
  }
  return 0;
}
export const over = (b) => !!winner(b) || b.every((col) => col.length >= ROWS);
export const margin = () => 0;

const winCol = (b, p) => legal(b).find((c) => winner(apply(b, c, p)) === p);
export function bot(b, seed, ply) {
  const win = winCol(b, 2); if (win != null) return win;                   // take the win
  const block = winCol(b, 1); if (block != null) return block;            // block your win
  const r = prng(seed + ":c4:" + ply);
  // avoid a column that lets YOU win on top next; prefer center
  const safe = legal(b).filter((c) => { const n = apply(b, c, 2); return winCol(n, 1) == null; });
  const pool = safe.length ? safe : legal(b);
  const order = [3, 2, 4, 1, 5, 0, 6].filter((c) => pool.includes(c));    // center-out preference
  const top = order.filter((c) => Math.abs(c - 3) === Math.abs(order[0] - 3));   // ties among equally-central
  return top[Math.floor(r() * top.length)];
}

// view(state, legal): 7x6 painted TOP row first (so the grid reads the way the pieces fall). A cell's move
// is its COLUMN, so tapping anywhere in a column drops there.
export const COLS_VIEW = 7;
export function view(b, legalMoves) {
  const ok = new Set(legalMoves || []);
  const cells = [];
  for (let r = ROWS - 1; r >= 0; r--) {
    for (let c = 0; c < COLS; c++) cells.push({ v: b[c][r] || 0, mv: ok.has(c) ? c : null });
  }
  return { cols: COLS, cells };
}
