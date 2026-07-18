/*
 * hexholm_solo_test.mjs — the provable daily gauntlet's soundness core: solo runs are deterministic,
 * a winning run's packed claim verifies to its exact score, and any tampering (words, count, day,
 * address) makes verifyClaim return -1. The "player" here is the same bot policy on seat 1, driven
 * through the exact soloState interleave every verifier replays.
 * Run: node tests/hexholm_solo_test.mjs
 */
import * as B from "../static/hexholm-bot.js";
import { prng } from "../static/hexholm-bot.js";

let fails = 0;
const ck = (n, c) => { console.log((c ? "PASS  " : "FAIL  ") + n); if (!c) fails++; };

function playSolo(seed) {                                   // ONE incremental interleave (O(n^2), not n^3)
  const recs = [], my = [];
  let st = B.soloReplay(seed, recs);
  let myEnds = 0;
  for (let guard = 0; guard < 900; guard++) {
    if (st.over || st.corrupt || st.blocked || myEnds >= B.SOLO_TURNS) break;
    if (B.botMustAct(st)) {
      const mv = B.pickMove(st, 2, prng(seed + ":bot:" + recs.length));
      if (mv == null) break;
      recs.push({ enc: mv, side: 2 });
    } else {
      if (my.length >= B.MAX_MY) break;
      const mv = B.pickMove(st, 1, prng(seed + ":me:" + my.length));
      if (mv == null) break;
      if (mv % 64 === 19) myEnds++;
      my.push(mv); recs.push({ enc: mv, side: 1 });
    }
    st = B.soloReplay(seed, recs);
  }
  return { st, my };
}

const DAY = 20600, ANCHOR = "ab12cd34ef56ab78" + "0".repeat(48), ADDR = "ndoTEST" + "T".repeat(41);
let won = null;
for (let i = 0; i < 3 && !won; i++) {
  const seed = B.seedOfDay(DAY + i, ANCHOR, ADDR);
  const r = playSolo(seed);
  const { st, used, done } = B.soloState(seed, r.my);
  if (done && !st.corrupt && used === r.my.length && r.my.length > 0 && r.my.length <= B.MAX_MY)
    won = { st, my: r.my, day: DAY + i, seed };
}
ck("a completed 12-turn daily exists within 3 seeds", !!won);
if (won) {
  const { my, day } = won;
  // determinism: replay from scratch reproduces the exact terminal state
  const again = B.soloState(won.seed, my).st;
  ck("solo replay deterministic", again.mi === won.st.mi && JSON.stringify(again.bank) === JSON.stringify(won.st.bank));
  const words = B.packRun(my), score = B.soloScore(won.st, my.length);
  ck("codec roundtrip", JSON.stringify(B.unpackRun(words, my.length)) === JSON.stringify(my));
  ck("honest claim verifies to its score (" + score + ")", B.verifyClaim(day, my.length, words, ANCHOR, ADDR) === score);
  const t1 = words.slice(); t1[0] = BigInt(Number(t1[0]) + 1);
  ck("tampered words -> -1", B.verifyClaim(day, my.length, t1, ANCHOR, ADDR) === -1);
  ck("wrong count -> -1", B.verifyClaim(day, Math.max(1, my.length - 3), words, ANCHOR, ADDR) === -1);
  ck("wrong day (different seed) -> -1", B.verifyClaim(day + 1, my.length, words, ANCHOR, ADDR) === -1);
  ck("stolen claim (other address) -> -1", B.verifyClaim(day, my.length, words, ANCHOR, "ndoTHIEF" + "X".repeat(40)) === -1);
  console.log(`   completed daily: ${my.length} player moves, ${B.SOLO_TURNS} turns -> score ${score}`);
}
console.log(fails ? "FAILURES: " + fails : "ALL PASS");
process.exit(fails ? 1 : 0);
