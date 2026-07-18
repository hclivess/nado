// hexholm-bot.js — the deterministic-seeded bot + the SOLO/PRACTICE machinery for HEXHOLM: powers the
// free practice-vs-computer mode, the PROVABLE DAILY GAUNTLET (provable.js model: a run is a pure
// function of (seed, my move list); the on-chain claim carries the move list and every verifier replays
// it), and the E2E move oracle. The bot is not clever, but it FINISHES games. Pure functions of
// (state, seat, rnd) / (seed, moves) — no DOM, no chain.
import * as E from "./hexholm-engine.js";
import { packMoves, unpackMoves, provableSeed } from "./provable.js";

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

// =====================================================================================================
// SOLO RUNS (practice + the provable daily gauntlet) — seat 1 = the player, seat 2 = this bot.
// EVERY derivation below is CONSENSUS FOR CLAIMS (all verifiers must replay byte-identically):
//   kh = 999 · rec i's seed height = 1000+i · q(h) = three 30-bit prng limbs · per-seat secrets from
//   the seed · commits [1,1] · the bot answers with pickMove(prng(seed+":bot:"+recIndex)) whenever it
//   is REQUIRED to act. A claim = the PLAYER'S move list only; the bot's replies re-derive.
// =====================================================================================================
export function soloQ(seed, h) {
  const rnd = prng(seed + ":" + h);
  return (BigInt(Math.floor(rnd() * 2 ** 30)) << 60n) + (BigInt(Math.floor(rnd() * 2 ** 30)) << 30n) +
         BigInt(Math.floor(rnd() * 2 ** 30));
}
export function soloSecrets(seed) {
  return { 1: soloQ(seed, 777771), 2: soloQ(seed, 777772) };
}
export function soloReplay(seed, recs) {
  return E.replay(soloQ(seed, 999),
    recs.map((r, i) => ({ enc: r.enc, side: r.side, q: soloQ(seed, 1000 + i) })),
    { cap: 2, secrets: soloSecrets(seed), commits: [1, 1] });
}
// the bot is REQUIRED to act when it heads the actor list, or owes a discard (free-actor phase)
export const botMustAct = (st) =>
  !st.over && !st.corrupt && !st.blocked &&
  (E.actorsNow(st)[0] === 2 || (st.phase === "discard" && st.players[2] && st.players[2].owe > 0));

// THE DAILY FORMAT: the run lasts exactly SOLO_TURNS player turns (or ends early if either side
// reaches 10 points) — bounded, always completable, always postable. Score = final victory points
// x101 + unused-move bonus, so more points ALWAYS outrank, and equal points rank by fewer moves.
export const SOLO_TURNS = 12;

// soloState(seed, myEncs): the canonical interleave — replay the player's encs in order, letting the
// bot answer between them; the run is DONE after the player's SOLO_TURNS-th end-turn (or game over).
// Returns {st, recs, used, done}; an illegal player enc leaves st.corrupt set.
export function soloState(seed, myEncs) {
  const recs = [];
  let used = 0, myEnds = 0, st = soloReplay(seed, recs);
  for (let guard = 0; guard < 1500; guard++) {
    if (st.over || st.corrupt || st.blocked || myEnds >= SOLO_TURNS) break;
    if (botMustAct(st)) {
      const mv = pickMove(st, 2, prng(seed + ":bot:" + recs.length));
      if (mv == null) break;
      recs.push({ enc: mv, side: 2 });
    } else if (used < myEncs.length) {
      const enc = myEncs[used++];
      if (enc % 64 === E.OP.END) myEnds++;
      recs.push({ enc, side: 1 });
    } else break;
    st = soloReplay(seed, recs);
  }
  return { st, recs, used, done: myEnds >= SOLO_TURNS || st.over };
}
export const soloScore = (st, n) => E.totalVp(st, 1) * 101 + (MAX_MY - n);

// ---- the provable daily claim (contract `post`) ----------------------------------------------------
export const MAX_MY = 100;                                 // player moves per daily run (fewest wins)
export const CLAIM_WORDS = 150;                            // 3 x 25-bit syms per enc, 2 syms per word
export const seedOfDay = (day, anchor, addr) => provableSeed("hexholm", day, anchor, addr);
const M25 = 1 << 25;
export function packRun(encs) {
  const syms = [];
  for (const e of encs) syms.push(e % M25, Math.floor(e / M25) % M25, Math.floor(e / (M25 * M25)));
  while (syms.length < MAX_MY * 3) syms.push(0);
  return packMoves(syms, 25).map(BigInt);
}
export function unpackRun(words, n) {
  const syms = unpackMoves(words.map(Number), 25, n * 3);
  const out = [];
  for (let i = 0; i < n; i++) out.push(syms[3 * i] + syms[3 * i + 1] * M25 + syms[3 * i + 2] * M25 * M25);
  return out;
}
// verifyClaim: replay a posted (day, n, words) claim — the TRUE score, or -1 for a bogus claim.
// The claim must be a COMPLETED daily (all SOLO_TURNS turns ended, or the game reached 10 points)
// that consumed exactly its n moves legally.
export function verifyClaim(day, n, words, anchor, addr) {
  if (!(n > 0 && n <= MAX_MY)) return -1;
  const encs = unpackRun(words, n);
  if (encs.some((e) => !(e > 0 && e < 2 ** 53))) return -1;
  const { st, used, done } = soloState(seedOfDay(day, anchor, addr), encs);
  if (st.corrupt || !done || used !== n) return -1;
  return soloScore(st, n);
}

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
