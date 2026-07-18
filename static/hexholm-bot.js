// hexholm-bot.js — a simple, deterministic-seeded bot for HEXHOLM: powers the free practice-vs-computer
// mode and the E2E move oracle. Not clever, but it FINISHES games: it always claims an available win,
// prefers building (keeps > homesteads > roads) over buying scrolls over bank trades, rolls when it must,
// and ends the turn when nothing else appeals. Pure function of (state, seat, rnd) — no DOM, no chain.
import * as E from "./hexholm-engine.js";

export function prng(seedStr) {                             // mulberry32 over a string hash
  let h = 1779033703 ^ seedStr.length;
  for (let i = 0; i < seedStr.length; i++) { h = Math.imul(h ^ seedStr.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
  return function () {
    h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16; return (h >>> 0) / 4294967296;
  };
}

const opOf = (e) => E.dec(e).op;
const PRIO = [E.OP.WIN, E.OP.KEEP, E.OP.STEAD, E.OP.SETUP, E.OP.ROAD, E.OP.BUY, E.OP.WARDEN,
              E.OP.PATH, E.OP.BOUNTY, E.OP.LEVY, E.OP.BANK, E.OP.ACCEPT, E.OP.DISCARD,
              E.OP.ROBBER, E.OP.ROLL, E.OP.END];

export function pickMove(st, seat, rnd) {
  const moves = E.legalMoves(st, seat);
  if (!moves.length) return null;
  // scroll plays: only sometimes (a bot that always wardens gets stuck shuffling the marauder)
  const playable = moves.filter((m) => {
    const op = opOf(m);
    if (op === E.OP.END) return true;
    if ([E.OP.WARDEN, E.OP.PATH, E.OP.BOUNTY, E.OP.LEVY].includes(op)) return rnd() < 0.35;
    if (op === E.OP.BANK) return rnd() < 0.5;
    if (op === E.OP.BUY) return rnd() < 0.6;
    return true;
  });
  const pool = playable.length ? playable : moves;
  for (const want of PRIO) {
    const of = pool.filter((m) => opOf(m) === want);
    if (!of.length) continue;
    if (want === E.OP.END && pool.some((m) => opOf(m) !== E.OP.END) && rnd() < 0.85) continue;
    return of[Math.floor(rnd() * of.length)];
  }
  return pool[Math.floor(rnd() * pool.length)];
}
