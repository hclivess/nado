// board-daily.js — shared harness for the FREE DAILY CHALLENGE on the 2-player board games (tic-tac-toe,
// connect four, reversi). The daily is a solo game vs a DETERMINISTIC bot seeded by the day's on-chain anchor
// + your address (per-player, non-transferable). You post only YOUR move list; the bot's replies are a pure
// function of the seed, so every browser AND the faucet oracle replay the exact game and agree on the score —
// a forged or copied claim never verifies. (doc/provable-practice.md + static/provable.js.) A game module
// supplies a pure `rules` object; this harness does the play/replay/score/verify.
//
// rules = {
//   SLUG, MOVE_BITS, MAX_MOVES,          // ids: game slug, bits per move, upper bound on total plies
//   start(),                             // -> fresh state (JSON-cloneable)
//   legal(state, player),               // -> [moves] for player (1=you, 2=bot)
//   apply(state, move, player),         // -> next state (may mutate + return)
//   over(state),                        // -> bool
//   winner(state),                      // -> 1 | 2 | 0 (0 = draw), meaningful once over()
//   bot(state, seed, ply),              // -> the bot's move (DETERMINISTIC in state+seed+ply)
//   margin(state),                      // -> your signed margin (reversi disc diff; 0 for the others)
// }
import { H, provableSeed, unpackMoves } from "./provable.js";

const WIN = 100, DRAW = 40;

// prng(seed): a deterministic 0..1 stream from the blake2b hash chain (the same H the provable SDK uses).
export function prng(seed) {
  let s = String(seed), n = 0;
  return () => { n++; return (parseInt(H(s + ":" + n).slice(0, 13), 16) % 1_000_000) / 1_000_000; };
}

// play(rules, seed, humanMoves): replay a game — you (player 1) move first from humanMoves in order, the bot
// (player 2) answers deterministically. Returns { over, winner, moves, plies, complete, illegal, state }.
export function play(rules, seed, humanMoves) {
  let state = rules.start(), player = 1, hi = 0, ply = 0;
  const moves = [];
  while (!rules.over(state) && ply <= rules.MAX_MOVES + 2) {
    let mv;
    if (player === 1) {
      if (hi >= humanMoves.length) break;                       // you stopped before the game ended
      mv = humanMoves[hi++];
      if (!rules.legal(state, 1).some((m) => m === mv)) return { illegal: true, complete: false };
    } else {
      const legal = rules.legal(state, 2);
      if (!legal.length) { player = 1; continue; }              // bot must pass (reversi) -> your turn again
      mv = rules.bot(state, seed, ply);
      if (!legal.some((m) => m === mv)) mv = legal[0];          // safety: bot never plays illegal
    }
    state = rules.apply(state, mv, player); moves.push(mv); ply++;
    player = 3 - player;
    if (player === 1 && !rules.legal(state, 1).length && !rules.over(state)) player = 2;   // you must pass
  }
  const over = rules.over(state);
  return { over, winner: over ? rules.winner(state) : 0, moves, plies: ply, complete: over, illegal: false, state };
}

// score a COMPLETED game (else -1): win rewards speed + margin, draw a flat middle, loss only your margin.
export function score(rules, r) {
  if (!r.complete || r.illegal) return -1;
  const m = Math.max(0, rules.margin ? rules.margin(r.state) : 0);
  if (r.winner === 1) return WIN + Math.max(0, rules.MAX_MOVES - r.plies) * 2 + m;
  if (r.winner === 0) return DRAW + m;
  return m;
}

// verifyClaim: unpack your moves, replay against the seed's bot, return the TRUE score (or -1 if malformed /
// illegal / unfinished). verifyEntries keeps a claim only when this equals the posted score.
export function verifyClaim(rules, day, n, words, anchorHash, addr) {
  n = Number(n);
  if (!(n > 0 && n <= rules.MAX_MOVES)) return -1;
  const moves = unpackMoves(words, rules.MOVE_BITS, n);
  const seed = provableSeed(rules.SLUG, day, anchorHash, addr);
  return score(rules, play(rules, seed, moves));
}
