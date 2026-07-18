/*
 * hexholm_daily_play.mjs — plays ONE complete daily island honestly (the player seat driven by the same
 * heuristic picker as the bot, with an end-turn budget so the run always finishes inside MAX_MY) and
 * prints the postable claim as one JSON line: {score, n, words, ok} — `ok` is a local verifyClaim
 * round-trip, so a false claim never even leaves this script. Used by the live daily E2E.
 * Usage: node tests/hexholm_daily_play.mjs <utcDay> <anchorValue> <addr>
 */
import * as E from "../static/hexholm-engine.js";
import { pickMove, prng, soloState, packRun, soloScore, seedOfDay, verifyClaim, MAX_MY }
  from "../static/hexholm-bot.js";

const [dayArg, anchor, addr] = process.argv.slice(2);
const day = Number(dayArg);
const seed = seedOfDay(day, anchor, addr);
const my = [];
let sinceEnd = 0;
for (let guard = 0; guard < 300; guard++) {
  const { st, done } = soloState(seed, my);
  if (done || st.corrupt) break;
  const moves = E.legalMoves(st, 1);
  if (!moves.length) break;
  let mv = pickMove(st, 1, prng(seed + ":me:" + my.length));
  if (mv == null) break;
  if (sinceEnd >= 4) {                                     // keep the run comfortably under MAX_MY
    const endMv = moves.find((m) => m % 64 === E.OP.END);
    if (endMv != null) mv = endMv;
  }
  sinceEnd = mv % 64 === E.OP.END ? 0 : sinceEnd + 1;
  my.push(mv);
  if (my.length >= MAX_MY) break;
}
const { st } = soloState(seed, my);
const score = soloScore(st, my.length);
const words = packRun(my).map(Number);
const ok = verifyClaim(day, my.length, words, anchor, addr) === score;
console.log(JSON.stringify({ score, n: my.length, words, ok, vp: E.totalVp(st, 1) }));
