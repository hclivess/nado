/*
 * stormhold-engine.js referee test: random-playout fuzzing over the REAL engine. For hundreds of seeded
 * games it generates only legal moves (mirroring what the UI lets a player submit), replays them through
 * the same replay() path the frontend uses, and asserts the invariants that make the game money-safe:
 *   - CARD CONSERVATION: supply + trash + both players' zones is constant (nothing minted or vanished)
 *   - the engine NEVER flags a legal move as corrupt
 *   - games TERMINATE (province drain or 3 empty piles) and score/tie-break computes
 *   - replay determinism: same log + same seeds => byte-identical state
 *   - blocked-seed behavior: a missing block hash pauses the replay, never corrupts it
 *   - illegal moves (wrong actor / bad payload) DO corrupt (the chess dispute model)
 * Run from the repo root:  node tests/stormhold_js_test.mjs
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/stormhold-engine.js");
const { CARDS, applyMove, init, replay, legalActor, encMove, computeResult, allCards, gainable, scoreOf } = E;

const isA = (id) => !!(CARDS[id].t & 1), isT = (id) => !!(CARDS[id].t & 2), isV = (id) => !!(CARDS[id].t & 4);
const SKIP = 4095;

import { prng, randomMove } from "./stormhold_bot.mjs";

const conserved = (st) => {
  let total = 0;
  for (const k of Object.keys(st.supply)) total += st.supply[k];
  total += st.trash.length + allCards(st, 0).length + allCards(st, 1).length;
  for (const f of st.frames) {   // in-flight cards riding inside decision frames
    if (f.cards) total += f.cards.length;               // sentry / bandit reveals
    if (f.card != null && f.t !== "tr2") total += 1;    // vassal / library reveal (tr2's card is in play)
    if (f.aside) total += f.aside.length;               // library set-asides
  }
  return total;
};

let fails = 0;
const check = (name, fn) => { try { fn(); console.log("PASS  " + name); } catch (e) { fails++; console.log("FAIL  " + name + ": " + (e && e.stack || e)); } };

// fake seed chain: every move gets a distinct deterministic q (stands in for bh(rh)+bh(rh+1))
const qOf = (game, i) => BigInt(game) * 1000003n + BigInt(i) * 7919n + 12345678901234567890n;

check("fuzz: 300 random games — conservation, termination, no false corrupt", () => {
  let ended = 0, longest = 0;
  for (let game = 0; game < 300; game++) {
    const rnd = prng(0xD0111 + game * 977);
    let st = init(7000 + game, qOf(game, -1));
    const total0 = conserved(st);
    const recs = [];
    for (let i = 0; i < 3000 && !st.over; i++) {
      st._q = qOf(game, recs.length);
      const mv = randomMove(st, rnd);
      applyMove(st, mv.side, mv.enc);
      recs.push({ ...mv, q: st._q });
      if (st.corrupt) throw new Error(`game ${game} corrupt after ${recs.length} moves: ${st.corruptWhy}`);
      if (conserved(st) !== total0) throw new Error(`game ${game}: card conservation broke (${conserved(st)} != ${total0})`);
    }
    longest = Math.max(longest, recs.length);
    if (st.over) {
      ended++;
      if (![1, 2, 3].includes(st.result)) throw new Error("bad result " + st.result);
      // replay determinism: re-derive through the frontend path and compare
      const st2 = replay(7000 + game, qOf(game, -1), recs);
      if (st2.corrupt || st2.blocked) throw new Error("replay diverged: " + (st2.corruptWhy || "blocked"));
      if (JSON.stringify(st2.ps) !== JSON.stringify(st.ps) || st2.result !== st.result)
        throw new Error("replay state mismatch");
      if (computeResult(st2) !== st.result) throw new Error("result recompute mismatch");
    }
  }
  if (ended < 250) throw new Error(`only ${ended}/300 games terminated (longest log ${longest})`);
  console.log(`      (${ended}/300 ended; longest move log ${longest})`);
});

check("scoring: gardens + tie-breaks", () => {
  const st = init(1, qOf(9, -1));
  // hand-craft: p0 has 2 gardens + 21 cards total -> gardens worth 2 each
  st.ps[0].deck = []; st.ps[0].hand = []; st.ps[0].disc = []; st.ps[0].play = [];
  st.ps[1].deck = []; st.ps[1].hand = []; st.ps[1].disc = []; st.ps[1].play = [];
  st.ps[0].disc = [16, 16].concat(Array(19).fill(0));            // 21 cards, 2 gardens -> 4 VP
  st.ps[1].disc = [3, 3, 3, 6];                                  // 3 estates - 1 curse -> 2 VP
  if (scoreOf(st, 0) !== 4 || scoreOf(st, 1) !== 2) throw new Error("VP calc");
  if (computeResult(st) !== 1) throw new Error("p1 should win");
  st.ps[1].disc.push(3);                                         // now 3 VP... still p0
  st.ps[1].disc.push(3);                                         // 4 VP tie
  st.ps[0].turns = 10; st.ps[1].turns = 9;
  if (computeResult(st) !== 2) throw new Error("tie: fewer turns wins");
  st.ps[1].turns = 10;
  if (computeResult(st) !== 3) throw new Error("equal turns: draw");
});

check("blocked seed pauses replay (never corrupts)", () => {
  const g = 4242, khQ = qOf(1, -1);
  const rnd = prng(7);
  // build a short legal prefix
  let st = init(g, khQ);
  const recs = [];
  for (let i = 0; i < 30 && !st.over; i++) {
    st._q = qOf(1, i);
    const mv = randomMove(st, rnd);
    applyMove(st, mv.side, mv.enc);
    recs.push({ ...mv, q: qOf(1, i) });
  }
  // find the first move that actually consumed randomness (end-turn redraw) and blank its q
  const recs2 = recs.map((r) => ({ ...r }));
  let st2 = replay(g, khQ, recs2);
  if (st2.corrupt) throw new Error("prefix corrupt?");
  // blank ALL qs after the first end-turn: replay must stop at the first shuffle-needing move
  let cut = recs2.findIndex((r) => r.enc % 16 === 4);
  if (cut < 0) cut = 5;
  for (let i = cut; i < recs2.length; i++) recs2[i].q = null;
  const st3 = replay(g, khQ, recs2);
  if (st3.corrupt) throw new Error("blocked replay corrupted");
  if (!(st3.blocked || st3.mi === recs2.length)) throw new Error("expected blocked or full replay");
  if (st3.blocked && st3.blockedAt < cut) throw new Error("blocked too early");
  // missing kingdom seed
  const st4 = replay(g, null, recs);
  if (!st4.blocked || !st4.setup) throw new Error("missing kh should block setup");
});

check("illegal moves corrupt (dispute model)", () => {
  const g = 5555, khQ = qOf(2, -1);
  let st = init(g, khQ);
  st._q = qOf(2, 0);
  applyMove(st, 2, encMove(4, 0));                       // p2 acting on p1's turn
  if (!st.corrupt) throw new Error("wrong actor accepted");
  st = init(g, khQ); st._q = qOf(2, 0);
  applyMove(st, 1, encMove(1, 12));                      // play out-of-range hand index
  if (!st.corrupt) throw new Error("bad play idx accepted");
  st = init(g, khQ); st._q = qOf(2, 0);
  applyMove(st, 1, encMove(3, 5));                       // buy a Province with 0 coins
  if (!st.corrupt) throw new Error("unaffordable buy accepted");
});

check("kingdom: 10 distinct piles, seed-determined", () => {
  const a = init(99, qOf(3, -1)), b = init(99, qOf(3, -1)), c = init(99, qOf(4, -1));
  if (new Set(a.kingdom).size !== 10) throw new Error("kingdom not 10 distinct");
  if (a.kingdom.some((id) => id < 7 || id > 32)) throw new Error("non-kingdom card picked");
  if (JSON.stringify(a.kingdom) !== JSON.stringify(b.kingdom)) throw new Error("not deterministic");
  if (JSON.stringify(a.kingdom) === JSON.stringify(c.kingdom)) throw new Error("seed ignored");
  if (a.ps[0].hand.length !== 5 || a.ps[1].hand.length !== 5) throw new Error("opening hands");
});

console.log(fails ? fails + " FAILURES" : "ALL PASS");
process.exit(fails ? 1 : 0);
