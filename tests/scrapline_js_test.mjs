/*
 * scrapline-engine.js referee test: random drafts over the REAL engine + the deterministic combat sim.
 * Asserts: offers are seed-determined; merges/scraps/skips follow the rules; illegal moves corrupt;
 * a missing seed BLOCKS the replay (never corrupts); replay is byte-deterministic; every finished draft
 * produces a decisive/draw result from a combat that both sides could recompute.
 * Run from the repo root:  node tests/scrapline_js_test.mjs
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/scrapline-engine.js");
const { ITEMS, ROUNDS, SLOTS, init, applyMove, replay, offerFor, encMove, simulate, BASE_HP } = E;

function prng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
const qOf = (game, i) => BigInt(game) * 1000003n + BigInt(i) * 7919n + 987654321987654321n;

let fails = 0;
const check = (name, fn) => { try { fn(); console.log("PASS  " + name); } catch (e) { fails++; console.log("FAIL  " + name + ": " + (e && e.stack || e)); } };

function draftGame(game, seed) {
  const rnd = prng(seed);
  let st = init(9000 + game, qOf(game, -1));
  const recs = [];
  while (!st.over) {
    // both players may act concurrently — alternate randomly among those still drafting
    const cand = [0, 1].filter((p) => st.ps[p].round < ROUNDS);
    const p = cand[Math.floor(rnd() * cand.length)];
    st._q = qOf(game, recs.length);
    const enc = rnd() < 0.12 ? encMove(2, 0)
      : encMove(1, Math.floor(rnd() * 3) + 4 * Math.floor(rnd() * SLOTS));
    applyMove(st, p + 1, enc);
    recs.push({ side: p + 1, enc, q: qOf(game, recs.length) });
    if (st.corrupt) throw new Error(`game ${game} corrupt: ${st.corruptWhy}`);
  }
  return { st, recs };
}

check("fuzz: 400 random drafts — combat resolves, replay deterministic", () => {
  const results = { 1: 0, 2: 0, 3: 0 };
  for (let game = 0; game < 400; game++) {
    const { st, recs } = draftGame(game, 0x5C4AB + game * 613);
    if (recs.length !== ROUNDS * 2) throw new Error("draft length " + recs.length);
    if (![1, 2, 3].includes(st.result)) throw new Error("bad result " + st.result);
    results[st.result]++;
    if (!st.combat || st.combat.result !== st.result) throw new Error("combat/result mismatch");
    const st2 = replay(9000 + game, qOf(game, -1), recs);
    if (st2.corrupt || st2.blocked) throw new Error("replay diverged");
    if (JSON.stringify(st2.ps.map((z) => [z.gear, z.maxhp])) !== JSON.stringify(st.ps.map((z) => [z.gear, z.maxhp])))
      throw new Error("replay build mismatch");
    if (st2.result !== st.result || st2.combat.hp.join() !== st.combat.hp.join()) throw new Error("replay combat mismatch");
  }
  console.log(`      (p1 ${results[1]} · p2 ${results[2]} · draw ${results[3]})`);
  if (results[1] + results[2] < 300) throw new Error("suspiciously many draws");
});

check("offers: seed-determined, tier gates respected", () => {
  const a = E.deriveOffer(7, 0, 1, qOf(1, -1)), b = E.deriveOffer(7, 0, 1, qOf(1, -1));
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error("not deterministic");
  const c = E.deriveOffer(7, 1, 1, qOf(1, -1));
  if (JSON.stringify(a) === JSON.stringify(c)) throw new Error("player salt ignored");
  for (let r = 1; r <= ROUNDS; r++) {
    const ok = r <= 3 ? [1] : r <= 6 ? [1, 2] : [2, 3];
    for (let s = 0; s < 40; s++) {
      const off = E.deriveOffer(7, s % 2, r, qOf(2, s));
      for (const id of off) if (!ok.includes(ITEMS[id].tier)) throw new Error(`round ${r} offered tier ${ITEMS[id].tier}`);
    }
  }
});

check("merge adds offer rank, replace scraps for max HP, skip pays scaled HP", () => {
  const g = 55, khQ = qOf(3, -1);
  let st = init(g, khQ);
  const off1 = offerFor(st, 0);
  st._q = qOf(3, 0); applyMove(st, 1, encMove(1, 0 + 4 * 2));            // pick choice 0 into slot 2
  if (st.ps[0].gear[2].id !== off1[0] || st.ps[0].gear[2].rank !== 1) throw new Error("pick failed");
  // find a follow-up offer containing the SAME item to merge (search rounds)
  let merged = false;
  for (let r = 0; r < 6 && !merged; r++) {
    const off = offerFor(st, 0);
    const j = off.indexOf(st.ps[0].gear[2].id);
    st._q = qOf(3, 10 + r);
    const expect = st.ps[0].gear[2].rank + E.offerRank(st.ps[0].round + 1);   // merge ADDS the offered rank
    if (j >= 0) { applyMove(st, 1, encMove(1, j + 4 * 2)); merged = true;
      if (st.ps[0].gear[2].rank !== Math.min(E.MAXRANK, expect)) throw new Error("merge didn't add offer rank"); }
    else applyMove(st, 1, encMove(2, 0));                                 // skip
  }
  // replace: put a DIFFERENT item onto slot 2 → maxhp grows by 15+10*(rank-1)
  for (let r = st.ps[0].round; r < ROUNDS - 1; r++) {
    const off = offerFor(st, 0);
    const j = off.findIndex((id) => id !== st.ps[0].gear[2].id);
    st._q = qOf(3, 40 + r);
    if (j >= 0) {
      const before = st.ps[0].maxhp, oldRank = st.ps[0].gear[2].rank;
      applyMove(st, 1, encMove(1, j + 4 * 2));
      if (st.ps[0].maxhp !== before + 15 + 10 * (oldRank - 1)) throw new Error("replace scrap credit wrong");
      break;
    }
    applyMove(st, 1, encMove(2, 0));
  }
  // skip pays scaled max HP: 8 + 4·(round being drafted), capped at 50
  const hp0 = st.ps[0].maxhp;
  if (st.ps[0].round < ROUNDS) { const exp = Math.min(50, 8 + 4 * (st.ps[0].round + 1));
    st._q = qOf(3, 99); applyMove(st, 1, encMove(2, 0));
    if (st.ps[0].maxhp !== hp0 + exp) throw new Error("skip credit wrong"); }
  if (st.corrupt) throw new Error("corrupt: " + st.corruptWhy);
});

check("illegal moves corrupt; missing seed blocks", () => {
  const g = 77, khQ = qOf(4, -1);
  let st = init(g, khQ); st._q = qOf(4, 0);
  applyMove(st, 1, encMove(1, 3 + 4 * 0));                                // choice 3 is out of range
  if (!st.corrupt) throw new Error("bad choice accepted");
  st = init(g, khQ); st._q = qOf(4, 0);
  applyMove(st, 1, encMove(7, 0));
  if (!st.corrupt) throw new Error("bad op accepted");
  st = init(g, khQ); st._q = qOf(4, 0);
  for (let r = 0; r < ROUNDS; r++) { st._q = qOf(4, r); applyMove(st, 1, encMove(2, 0)); }
  st._q = qOf(4, 99); applyMove(st, 1, encMove(2, 0));
  if (!st.corrupt) throw new Error("over-drafting accepted");
  // blocked: second move's offer derives from first move's q — blank it
  const recs = [{ side: 1, enc: encMove(2, 0), q: null }, { side: 1, enc: encMove(2, 0), q: null }];
  const st2 = replay(g, khQ, recs);
  if (st2.corrupt) throw new Error("blocked replay corrupted");
  if (!st2.blocked || st2.blockedAt !== 1) throw new Error("expected block at move 1, got " + st2.blockedAt);
});

check("combat: deterministic, symmetric builds draw, more gear beats none", () => {
  const mk = () => { const st = init(1, qOf(5, -1)); st.ps[0].round = ROUNDS; st.ps[1].round = ROUNDS; return st; };
  let st = mk();
  st.ps[0].gear[0] = { id: 0, rank: 2 }; st.ps[1].gear[0] = { id: 0, rank: 2 };
  const s1 = simulate(st), s2 = simulate(st);
  if (s1.result !== 3) throw new Error("mirror build should draw, got " + s1.result);
  if (JSON.stringify(s1.hp) !== JSON.stringify(s2.hp)) throw new Error("sim not deterministic");
  st = mk();
  st.ps[0].gear[0] = { id: 8, rank: 3 }; st.ps[0].gear[1] = { id: 12, rank: 2 }; st.ps[0].gear[2] = { id: 4, rank: 2 };
  if (simulate(st).result !== 1) throw new Error("armed vs unarmed should win");
  // spark double vs shield: tesla (22) vs boilerplate wall should still break through faster than plain
  st = mk();
  st.ps[0].gear[0] = { id: 22, rank: 2 };
  st.ps[1].gear[0] = { id: 12, rank: 4 };
  if (simulate(st).result !== 1) throw new Error("spark should beat pure shield (meltdown otherwise)");
});

check("solo gauntlet: deterministic, escalating, always terminates", () => {
  // determinism: same seed + same choices => identical runs
  const play = (seed, seedRnd, maxIters) => {
    const rnd = prng(seedRnd);
    const run = E.soloNew(seed);
    let iters = 0;
    while (!run.over && iters++ < maxIters) {
      while (run.picks > 0 && !run.over) {
        const offer = E.soloOfferFor(run);
        if (!offer) throw new Error("no offer while alive with picks left");
        if (rnd() < 0.1) E.soloPick(run, -1, 0);
        else {
          const choice = Math.floor(rnd() * 3);
          let slot = run.gear.findIndex((g) => g && g.id === offer[choice] && g.rank < E.MAXRANK);
          if (slot < 0) slot = run.gear.findIndex((g) => !g);
          if (slot < 0) slot = Math.floor(rnd() * E.SLOTS);
          E.soloPick(run, choice, slot);
        }
      }
      E.soloFight(run);
    }
    return { run, iters };
  };
  const a = play("daily-2026-07-16", 42, 600), b = play("daily-2026-07-16", 42, 600);
  if (JSON.stringify(a.run) !== JSON.stringify(b.run)) throw new Error("solo run not deterministic");
  const c = play("other-seed", 42, 600);
  if (JSON.stringify(a.run.gear) === JSON.stringify(c.run.gear)) throw new Error("seed ignored");
  // 200 random runs: all terminate, scores are sane, enemies escalate
  let best = 0, total = 0, clear1 = 0;
  for (let i = 0; i < 200; i++) {
    const { run, iters } = play("fuzz-" + i, 977 * i + 5, 800);
    if (!run.over) throw new Error("run " + i + " never ended (" + iters + " iters, stage " + run.stage + ")");
    if (run.score !== run.stage - 1) throw new Error("score bookkeeping");
    if (run.score >= 1) clear1++;
    best = Math.max(best, run.score); total += run.score;
  }
  console.log(`      (200 RANDOM-bot runs: avg ${(total / 200).toFixed(1)}, best ${best}, stage-1 clear ${(clear1 / 2).toFixed(0)}%)`);
  // the curve contract (validated by tests/scrapline_sim_lab.mjs — random is the floor, synergy must beat it):
  if (clear1 < 150) throw new Error("stage 1 too brutal (" + clear1 + "/200 clears)");
  if (total / 200 < 3) throw new Error("gauntlet too hard — tune the curve (avg " + (total / 200).toFixed(1) + ")");
  if (total / 200 > 15 || best > 60) throw new Error("gauntlet too easy / immortal build — tune the curve");
  // SYNERGY FLOOR (the brick-wall + depth regression guard): a merge-first single-tag drafter must
  // clearly beat random — this is the cheap in-CI proxy for the sim lab's 2x depth requirement.
  const arch = (tag) => (run) => {
    const offer = E.soloOfferFor(run);
    for (let c = 0; c < 3; c++) {
      const s = run.gear.findIndex((g) => g && g.id === offer[c] && g.rank < E.MAXRANK);
      if (s >= 0) return { c, s };
    }
    for (let c = 0; c < 3; c++) {
      const it = E.ITEMS[offer[c]];
      if (it.tag === tag || (it.kind === "c" && (it.ctag === tag || it.call))) {
        const s = run.gear.findIndex((g) => !g);
        if (s >= 0) return { c, s };
      }
    }
    return { c: -1, s: 0 };
  };
  let archTotal = 0, archBest = 0;
  for (let i = 0; i < 120; i++) {
    const run = E.soloNew("arch-" + i), pol = arch(i % 2);   // blade / bolt
    let guard = 0;
    while (!run.over && guard++ < 300) {
      while (run.picks > 0 && !run.over) { const a = pol(run); if (!E.soloPick(run, a.c, a.s)) E.soloPick(run, -1, 0); }
      E.soloFight(run);
    }
    if (!run.over) throw new Error("arch run " + i + " never ended (immortal build leak)");
    archTotal += run.score; archBest = Math.max(archBest, run.score);
  }
  const archAvg = archTotal / 120, rndAvg = total / 200;
  console.log(`      (120 SYNERGY-bot runs: avg ${archAvg.toFixed(1)}, best ${archBest} — vs random avg ${rndAvg.toFixed(1)})`);
  if (archAvg < rndAvg * 1.4) throw new Error("interplay too shallow — synergy drafting must beat random (lab target 2x)");
  if (archBest > 100) throw new Error("immortal build — late-game pressure failed");
  const e1 = E.enemyBuild("x", 1), e9 = E.enemyBuild("x", 9);
  if (!(e9.maxhp > e1.maxhp)) throw new Error("enemy hull should escalate");
  if (JSON.stringify(E.enemyBuild("x", 4)) !== JSON.stringify(E.enemyBuild("x", 4))) throw new Error("enemy not deterministic");
  if (!e1.gear.some((g) => g && E.ITEMS[g.id].kind === "d")) throw new Error("stage-1 enemy must carry a weapon");
});

check("daily claims: pack/unpack roundtrip, honest claims verify, fakes + copies rejected", () => {
  const day = 20650, anchor = "ab12cd34ef56ab78" + "0".repeat(48), addr = "ndotestplayer" + "a".repeat(36);
  const seed = E.seedOfDay(day, anchor, addr);
  // play an honest daily run recording choices
  const rnd = prng(99);
  const run = E.soloNew(seed);
  let guard = 0;
  while (!run.over && guard++ < 300) {
    const offer = E.soloOfferFor(run);
    if (rnd() < 0.1) E.soloPick(run, -1, 0);
    else {
      const choice = Math.floor(rnd() * 3);
      let slot = run.gear.findIndex((g) => g && g.id === offer[choice] && g.rank < E.MAXRANK);
      if (slot < 0) slot = run.gear.findIndex((g) => !g);
      if (slot < 0) slot = Math.floor(rnd() * E.SLOTS);
      E.soloPick(run, choice, slot);
    }
    E.soloFight(run);
  }
  if (!run.over) throw new Error("run never ended");
  if (run.choices.length !== run.offerN) throw new Error("choice recording out of sync");
  const words = E.packChoices(run.choices);
  if (words.some((w) => w >= 2n ** 50n)) throw new Error("packed word too big for JSON numbers");
  const back = E.unpackChoices(words.map(Number), run.choices.length);
  if (JSON.stringify(back) !== JSON.stringify(run.choices)) throw new Error("pack/unpack roundtrip");
  // honest claim verifies to the true score (via JSON-number words, like the chain view returns them)
  if (E.verifyClaim(day, run.choices.length, words.map(Number), anchor, addr) !== run.score) throw new Error("honest claim rejected");
  // fakes: inflated score is exposed (verify returns the TRUE score, board compares), wrong day rejected,
  // truncated run (not over) rejected, garbage rejected
  if (E.verifyClaim(day, run.choices.length, words.map(Number), anchor, addr) === run.score + 5) throw new Error("inflated score verified?!");
  if (E.verifyClaim(day + 1, run.choices.length, words.map(Number), anchor, addr) === run.score) throw new Error("wrong-day claim verified");
  if (run.choices.length > 3 && E.verifyClaim(day, 2, words.map(Number), anchor, addr) !== -1) throw new Error("unfinished run accepted");
  const g = E.verifyClaim(day, 50, [31, 31, 31, 31, 31], anchor, addr);
  if (g !== -1 && g > 0) throw new Error("garbage produced a positive score");
  if (E.verifyClaim(day, 0, words.map(Number), anchor, addr) !== -1) throw new Error("n=0 accepted");
  // COPY-THEFT: the same move list must NOT verify for a different poster (the seed binds the address)
  const thief = "ndothiefthief" + "b".repeat(36);
  if (E.verifyClaim(day, run.choices.length, words.map(Number), anchor, thief) === run.score)
    throw new Error("copied claim verified for a different address");
  // PRE-GRIND: a different day anchor (i.e. a run ground against a guessed anchor) must not verify
  if (E.verifyClaim(day, run.choices.length, words.map(Number), "ff".repeat(32), addr) === run.score)
    throw new Error("wrong-anchor claim verified");
});

console.log(fails ? fails + " FAILURES" : "ALL PASS");
process.exit(fails ? 1 : 0);
