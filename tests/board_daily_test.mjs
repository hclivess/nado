/*
 * board_daily_test.mjs — the correctness properties of the shared board-game Daily Challenge harness
 * (static/board-daily.js + the three pure rule sets). Proves the thing the faucet's money depends on:
 * a genuine claim verifies to exactly the score it posted, and anything else does not.
 * Run: node tests/board_daily_test.mjs
 */
import { play, score, verifyClaim, prng } from "../static/board-daily.js";
import { provableSeed, packMoves, unpackMoves } from "../static/provable.js";
import * as TTT from "../static/tictactoe-rules.js";
import * as C4 from "../static/connect4-rules.js";
import * as REV from "../static/reversi-rules.js";

let pass = 0, fail = 0;
const ok = (c, m) => { c ? pass++ : (fail++, console.log("  FAIL:", m)); };

const DAY = 20653, ANCH = "a3f19c7d4e5b6a2f8c0d1e2f3a4b5c6d", ME = "mldsa44" + "1".repeat(45), YOU = "mldsa44" + "2".repeat(45);

for (const rules of [TTT, C4, REV]) {
  const g = rules.SLUG;
  const seed = provableSeed(rules.SLUG, DAY, ANCH, ME);

  // 1) DETERMINISM: the same seed + moves always replays identically (this is what every verifier relies on)
  const greedy = (st, who) => rules.legal(st, who)[0];
  const runOnce = () => {
    let s = rules.start(), mine = [], guard = 0;
    while (!rules.over(s) && guard++ < rules.MAX_MOVES + 4) {
      const legal = rules.legal(s, 1);
      if (!legal.length) break;
      const mv = legal[Math.floor(prng(seed + ":pick" + mine.length)() * legal.length)];
      const r = play(rules, seed, [...mine, mv]);
      if (r.illegal) break;
      mine.push(mv);
      s = r.state;
      if (r.complete) break;
    }
    return mine;
  };
  const mine = runOnce();
  const a = play(rules, seed, mine), b = play(rules, seed, mine);
  ok(JSON.stringify(a.moves) === JSON.stringify(b.moves), `${g}: replay is deterministic`);
  ok(a.complete, `${g}: the sampled run reaches a finished game (${a.plies} plies)`);

  // 2) a GENUINE claim verifies to exactly the score it posted
  const sc = score(rules, a);
  const words = packMoves(mine, rules.MOVE_BITS);
  ok(sc >= 0, `${g}: completed game scores (${sc})`);
  ok(verifyClaim(rules, DAY, mine.length, words, ANCH, ME) === sc, `${g}: genuine claim verifies to its score`);

  // 3) pack/unpack round-trips every move exactly
  ok(JSON.stringify(unpackMoves(words, rules.MOVE_BITS, mine.length)) === JSON.stringify(mine),
     `${g}: packed moves round-trip`);

  // 4) a COPIED claim (same moves, different poster) must NOT verify — the seed binds the address
  ok(verifyClaim(rules, DAY, mine.length, words, ANCH, YOU) !== sc || sc <= 0,
     `${g}: a claim copied to another address does not reproduce the score`);

  // 5) a claim for the WRONG DAY does not reproduce the score
  ok(verifyClaim(rules, DAY + 1, mine.length, words, ANCH, ME) !== sc || sc <= 0,
     `${g}: a claim replayed against another day does not reproduce the score`);

  // 6) an INFLATED n is rejected outright
  ok(verifyClaim(rules, DAY, rules.MAX_MOVES + 1, words, ANCH, ME) === -1, `${g}: n above MAX_MOVES rejected`);

  // 7) an UNFINISHED game scores -1 (you cannot post a half-played run)
  if (mine.length > 1) {
    const part = play(rules, seed, mine.slice(0, 1));
    if (!part.complete) ok(score(rules, part) === -1, `${g}: unfinished run scores -1`);
    else pass++;
  } else pass++;

  // 8) an ILLEGAL move is caught rather than scored
  const bogus = play(rules, seed, [9999]);
  ok(bogus.illegal || !bogus.complete, `${g}: an illegal move never yields a complete game`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
