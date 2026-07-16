/*
 * stormhold_hidden_test.mjs — lockstep fuzz for HIDDEN-HANDS mode. For each seeded game it advances FOUR
 * states through the same claim-carrying move log:
 *   exact — verify mode (both secrets): the ground truth, every claim asserted
 *   pov0 / pov1 — what each player's browser actually sees (own zones real, opponent = UNKNOWN counts)
 * and asserts after EVERY move that the public projection agrees across all three (supply, trash size,
 * coins/actions/buys/turn/phase, zone counts, frame stack shape, and the PUBLIC play areas — plays stay
 * visible like the real game). At game end verifyHidden must reproduce the exact result with no cheater,
 * and a TAMPERED claim (lying about the played card) must convict the liar.
 * Run: node tests/stormhold_hidden_test.mjs
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/stormhold-engine.js");
const { init, applyMove, replay, verifyHidden, mixQ, encMove, UNKNOWN, CARDS } = E;
import { prng, randomMoveHidden } from "./stormhold_bot.mjs";

let fails = 0;
const check = (name, fn) => { try { fn(); console.log("PASS  " + name); } catch (e) { fails++; console.log("FAIL  " + name + ": " + (e && e.stack || e)); } };
const qOf = (game, i) => BigInt(game) * 1000003n + BigInt(i) * 7919n + 12345678901234567890n;

const proj = (st) => JSON.stringify({
  supply: st.supply, trash: st.trash.length, coins: st.coins, actions: st.actions, buys: st.buys,
  turn: st.turn, phase: st.phase, over: st.over,
  z: st.ps.map((z) => [z.deck.length, z.hand.length, z.disc.length, z.play.length, z.turns]),
  frames: st.frames.map((f) => f.t + ":" + f.p),
});
// the play areas are PUBLIC: a pov replay must materialize the same card ids the exact replay holds
const plays = (st) => JSON.stringify(st.ps.map((z) => z.play));

check("hidden fuzz: 120 games — pov projections track exact, claims verify, games end", () => {
  let ended = 0, longest = 0;
  for (let game = 0; game < 120; game++) {
    const rnd = prng(0x51DE + game * 977);
    const secrets = [qOf(game, 900001), qOf(game, 900002)];
    const khQ = qOf(game, -1);
    const kq = (mine) => ({ pub: khQ, 0: mine === "x" || mine === 0 ? mixQ(khQ, secrets[0]) : null,
                            1: mine === "x" || mine === 1 ? mixQ(khQ, secrets[1]) : null });
    const stE = init(9000 + game, kq("x"), 0, { pov: null });
    const st0 = init(9000 + game, kq(0), 0, { pov: 0 });
    const st1 = init(9000 + game, kq(1), 0, { pov: 1 });
    if (proj(stE) !== proj(st0) || proj(stE) !== proj(st1)) throw new Error("game " + game + ": setup projection mismatch");
    const recs = [];
    for (let i = 0; i < 3000 && !stE.over; i++) {
      const mv = randomMoveHidden(stE, rnd);
      const q = qOf(game, recs.length);
      const qs = (mine) => ({ pub: q, 0: mine === "x" || mine === 0 ? mixQ(q, secrets[0]) : null,
                              1: mine === "x" || mine === 1 ? mixQ(q, secrets[1]) : null });
      stE._q = qs("x"); applyMove(stE, mv.side, mv.enc);
      if (stE.corrupt) throw new Error(`game ${game} EXACT corrupt after ${recs.length + 1}: ${stE.corruptWhy}`);
      st0._q = qs(0); applyMove(st0, mv.side, mv.enc);
      if (st0.corrupt) throw new Error(`game ${game} POV0 corrupt after ${recs.length + 1}: ${st0.corruptWhy}`);
      st1._q = qs(1); applyMove(st1, mv.side, mv.enc);
      if (st1.corrupt) throw new Error(`game ${game} POV1 corrupt after ${recs.length + 1}: ${st1.corruptWhy}`);
      recs.push({ enc: mv.enc, side: mv.side, q });
      if (proj(stE) !== proj(st0) || proj(stE) !== proj(st1))
        throw new Error(`game ${game} projection diverged at move ${recs.length}\nE ${proj(stE)}\n0 ${proj(st0)}\n1 ${proj(st1)}`);
      if (plays(stE) !== plays(st0) || plays(stE) !== plays(st1))
        throw new Error(`game ${game} public play areas diverged at move ${recs.length}`);
      // each pov's OWN zones must be the exact truth (their secret derives their real cards)
      for (const [st, p] of [[st0, 0], [st1, 1]]) {
        if (JSON.stringify(st.ps[p]) !== JSON.stringify(stE.ps[p]))
          throw new Error(`game ${game} pov${p} own-zone mismatch at move ${recs.length}`);
        if (st.ps[1 - p].hand.some((c) => c === undefined)) throw new Error("undefined card leaked");
      }
    }
    longest = Math.max(longest, recs.length);
    if (stE.over) {
      ended++;
      // the reveal pass: full-log verification with both secrets — no cheater, same result
      const v = verifyHidden(9000 + game, khQ, recs, 0, secrets);
      if (v.corrupt || v.cheater) throw new Error(`game ${game} honest reveal flagged: ${v.corruptWhy}`);
      if (v.result !== stE.result) throw new Error(`game ${game} reveal result ${v.result} != ${stE.result}`);
      if (![1, 2, 3].includes(v.result)) throw new Error("bad result");
      // pov replays must NOT know the result (opponent decks are hidden)
      if (st0.result !== 0 || st1.result !== 0) throw new Error("pov leaked a result");
    }
  }
  if (ended < 100) throw new Error(`only ${ended}/120 hidden games terminated (longest ${longest})`);
  console.log(`      (${ended}/120 ended; longest move log ${longest})`);
});

check("cheat detection: a lied PLAY claim convicts the mover at reveal", () => {
  for (let game = 0; game < 40; game++) {
    const rnd = prng(0xBAD + game * 31);
    const secrets = [qOf(game, 800001), qOf(game, 800002)];
    const khQ = qOf(game, -2);
    const stE = init(9500 + game, { pub: khQ, 0: mixQ(khQ, secrets[0]), 1: mixQ(khQ, secrets[1]) }, 0, { pov: null });
    const recs = [];
    let tampered = -1, tamperSide = 0;
    for (let i = 0; i < 400 && !stE.over; i++) {
      const mv = randomMoveHidden(stE, rnd);
      const q = qOf(game, 7000 + i);
      stE._q = { pub: q, 0: mixQ(q, secrets[0]), 1: mixQ(q, secrets[1]) };
      applyMove(stE, mv.side, mv.enc);
      recs.push({ enc: mv.enc, side: mv.side, q });
    }
    // tamper the FIRST action play: claim a different action card than the one actually at that index
    for (let i = 0; i < recs.length; i++) {
      const op = recs[i].enc % 16;
      if (op === 1) {
        const payload = Math.floor(recs[i].enc / 16), idx = payload % 32, card = Math.floor(payload / 32) % 64;
        const lie = card === 13 ? 21 : 13;                    // claim Waystation/Scribe instead
        recs[i] = { ...recs[i], enc: encMove(1, idx + lie * 32) };
        tampered = i; tamperSide = recs[i].side;
        break;
      }
    }
    if (tampered < 0) continue;                               // no action played this game — skip
    const v = verifyHidden(9500 + game, khQ, recs, 0, secrets);
    if (!(v.corrupt || v.cheater)) throw new Error(`game ${game}: tampered claim sailed through reveal`);
    if (v.cheater && v.cheater !== tamperSide) throw new Error(`game ${game}: wrong cheater (${v.cheater} != ${tamperSide})`);
  }
});

console.log(fails ? fails + " FAILURES" : "ALL PASS");
process.exit(fails ? 1 : 0);
