/*
 * hexholm_engine_test.mjs — headless soak of the HEXHOLM rules engine: geometry sanity, then full
 * random-bot self-play games at 2/3/4 seats over many seeds, replayed MOVE BY MOVE through the exact
 * replay() the browser uses. Invariants after every move: resource conservation (bank + all hands = 19
 * of each), no negative counts, supply caps, no corruption from bot moves (the bot only emits
 * legalMoves() output — a corrupt flag means referee and generator disagree = a real bug).
 * Run: node tests/hexholm_engine_test.mjs [games-per-cap]
 */
import * as E from "../static/hexholm-engine.js";
import { prng, pickMove } from "../static/hexholm-bot.js";

let fails = 0;
const ck = (n, c) => { console.log((c ? "PASS  " : "FAIL  ") + n); if (!c) fails++; };

// ---- geometry --------------------------------------------------------------------------------------
ck("19 hexes", E.NHEX === 19);
ck("54 vertices", E.NVERT === 54);
ck("72 edges", E.NEDGE === 72);
ck("30 coastal edges in one ring", E.GEO.ring.length === 30);
ck("9 harbors", E.GEO.PORT_AT.length === 9);
ck("every vertex touches 1-3 hexes", E.GEO.verts.every((v) => v.hexes.length >= 1 && v.hexes.length <= 3));
ck("every vertex has 2-3 edges", E.GEO.verts.every((v) => v.edges.length >= 2 && v.edges.length <= 3));

// ---- layout ----------------------------------------------------------------------------------------
const q0 = 123456789123456789n;
const lay = E.layout(q0, 4);
ck("layout: one Wastes hex", lay.tiles.filter((t) => t === -1).length === 1);
ck("layout: 18 tokens", lay.tokens.filter((t) => t > 0).length === 18);
ck("layout: token bag exact", JSON.stringify(lay.tokens.filter(Boolean).sort((a, b) => a - b)) ===
   JSON.stringify([2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]));
const hot = (i) => lay.tokens[i] === 6 || lay.tokens[i] === 8;
ck("layout: no adjacent 6/8", !E.GEO.hexes.some((h, i) => hot(i) && h.nbr.some(hot)));
ck("layout: deterministic", JSON.stringify(E.layout(q0, 4)) === JSON.stringify(lay));

// ---- self-play soak --------------------------------------------------------------------------------
const GAMES = Number(process.argv[2] || 6);
const fakeQ = (seed, h) => {                                // deterministic per-height BigInt seed
  const rnd = prng(seed + ":" + h);
  return (BigInt(Math.floor(rnd() * 2 ** 30)) << 60n) + (BigInt(Math.floor(rnd() * 2 ** 30)) << 30n) +
         BigInt(Math.floor(rnd() * 2 ** 30));
};

let finished = 0, totalMoves = 0, maxMoves = 0;
for (const cap of [2, 3, 4]) {
  for (let g = 0; g < GAMES; g++) {
    const seedTag = "soak-" + cap + "-" + g;
    const secrets = {}; for (let s = 1; s <= cap; s++) secrets[s] = fakeQ(seedTag + "-x", s) % (2n ** 60n);
    const rnd = prng(seedTag);
    const recs = [];
    let st = null, ok = true;
    for (let mv = 0; mv < 999; mv++) {
      st = E.replay(fakeQ(seedTag, 0), recs, { cap, secrets });
      if (st.corrupt) { ck(seedTag + " no corruption (move " + mv + ": " + st.why + ")", false); ok = false; break; }
      // conservation: bank + hands == 19 per resource
      for (let r = 0; r < 5; r++) {
        let sum = st.bank[r];
        for (let s = 1; s <= cap; s++) { sum += st.players[s].res[r];
          if (st.players[s].res[r] < 0) { ck(seedTag + " non-negative hand", false); ok = false; } }
        if (sum !== E.BANK_EACH) { ck(seedTag + " conservation r" + r + " (" + sum + ")", false); ok = false; }
      }
      for (let s = 1; s <= cap; s++) { const p = st.players[s];
        if (p.roads.size > 15 || p.steads.size > 5 || p.keeps.size > 4) { ck(seedTag + " supply caps", false); ok = false; } }
      if (!ok || st.over) break;
      // pick an actor with a move (rotate through actorsNow)
      const actors = E.actorsNow(st);
      let played = false;
      for (const s of actors) {
        const m = pickMove(st, s, rnd);
        if (m != null) { recs.push({ enc: m, side: s, q: fakeQ(seedTag, 100 + recs.length) }); played = true; break; }
      }
      if (!played) { ck(seedTag + " actor had no legal move", false); ok = false; break; }
    }
    if (!ok) continue;
    totalMoves += recs.length; maxMoves = Math.max(maxMoves, recs.length);
    if (st.over && st.winner) {
      finished++;
      const v = E.totalVp(st, st.winner);
      if (v < E.WIN_VP) ck(seedTag + " winner really has 10+ (got " + v + ")", false);
    }
  }
}
ck("all self-play games clean", fails === 0);
console.log(`self-play: ${finished}/${GAMES * 3} finished with a win, avg moves ${(totalMoves / (GAMES * 3)) | 0}, max ${maxMoves}`);
ck("a majority of games reach a win under the move cap", finished >= GAMES * 3 * 0.5);
console.log(fails ? "FAILURES: " + fails : "ALL PASS");
process.exit(fails ? 1 : 0);
