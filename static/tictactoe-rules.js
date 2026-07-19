// tictactoe-rules.js — pure rules + a deterministic, beatable bot for the free Daily Challenge (shared by
// tictactoe.js and tests/tictactoe_daily_verify.mjs via board-daily.js). No DOM. You are player 1 (✕), the
// seeded bot is player 2 (◯). The bot takes a win, else blocks a loss, else plays center/corner/edge with a
// seeded tie-break — good but NOT perfect, so a sharp player can fork it and win.
import { prng } from "./board-daily.js";

export const SLUG = "tictactoe", MOVE_BITS = 4, MAX_MOVES = 9;
const LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];

export const start = () => Array(9).fill(0);
export const legal = (b) => { const o = []; for (let i = 0; i < 9; i++) if (!b[i]) o.push(i); return o; };
export const apply = (b, mv, p) => { const n = b.slice(); n[mv] = p; return n; };
export function winner(b) { for (const [a, c, d] of LINES) if (b[a] && b[a] === b[c] && b[a] === b[d]) return b[a]; return 0; }
export const over = (b) => !!winner(b) || b.every((x) => x);
export const margin = () => 0;

// win-for(p): a cell that completes a line for p, else -1.
function winMove(b, p) {
  for (const ln of LINES) { const v = ln.map((i) => b[i]); if (v.filter((x) => x === p).length === 2 && v.includes(0)) return ln[v.indexOf(0)]; }
  return -1;
}
export function bot(b, seed, ply) {
  const win = winMove(b, 2); if (win >= 0) return win;              // take the win
  const block = winMove(b, 1); if (block >= 0) return block;        // block your win
  const r = prng(seed + ":ttt:" + ply);
  const open = legal(b);
  for (const pref of [[4], [0, 2, 6, 8], [1, 3, 5, 7]]) {           // center, then corners, then edges
    const cands = pref.filter((i) => !b[i]);
    if (cands.length) return cands[Math.floor(r() * cands.length)]; // seeded tie-break
  }
  return open[Math.floor(r() * open.length)];
}

// view(state, legal): the display grid, so ONE shared renderer (board-daily-ui.js) can paint every board
// game. cells run left-to-right, top-to-bottom; `mv` is the move that plays that cell (null = not playable).
export const COLS_VIEW = 3;
export function view(b, legalMoves) {
  const ok = new Set(legalMoves || []);
  return { cols: 3, cells: b.map((v, i) => ({ v, mv: ok.has(i) ? i : null })) };
}
