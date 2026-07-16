/*
 * scrapline_sim_lab.mjs — the BALANCE LABORATORY: measures the solo gauntlet with real policies instead
 * of a random bot, because random play only proves the floor. Policies:
 *   random     — the accessibility floor
 *   hpstack    — skip/scrap everything for max HP (degenerate stat-stuffing; must NOT be optimal)
 *   arch:<tag> — synergy drafters: prefer one tag + its CORE buffs, merge-first (interplay depth probes)
 *   search     — near-optimal: enumerates BOTH picks before each fight jointly (19×19 actions) and
 *                scores each pair by simulating the actual deterministic combat vs the actual next
 *                enemy. This is the skill CEILING — humans land between arch and search.
 * Outputs: score distribution per policy (median/p90/max), the smart-vs-random depth ratio, per-stage
 * marginal winrates for the search bot (the brick-wall detector — a fair curve declines smoothly; a
 * wall shows as a cliff to ~0%), and a no-CORE ablation (how much the buff economy matters).
 * Run:  node tests/scrapline_sim_lab.mjs [runsPerPolicy=60]
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/scrapline-engine.js");
const { ITEMS, SLOTS, MAXRANK, soloNew, soloOfferFor, soloPick, soloFight, enemyBuild, simulateBuilds, itemVal } = E;

const RUNS = parseInt(process.argv[2] || "60", 10);
const isCore = (id) => ITEMS[id].kind === "c";
const isDmg = (id) => ITEMS[id].kind === "d";
function prng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }

// ---- policies: pick(run, rnd) -> {choice(-1=skip), slot} ------------------------------------------------
const policies = {};

policies.random = (run, rnd) => {
  if (rnd() < 0.1) return { choice: -1, slot: 0 };
  const offer = soloOfferFor(run), choice = Math.floor(rnd() * 3);
  let slot = run.gear.findIndex((g) => g && g.id === offer[choice] && g.rank < MAXRANK);
  if (slot < 0) slot = run.gear.findIndex((g) => !g);
  if (slot < 0) slot = Math.floor(rnd() * SLOTS);
  return { choice, slot };
};

policies.hpstack = (run) => {
  // keep the starter shiv, scrap everything else for max HP — the degenerate baseline
  return { choice: -1, slot: 0 };
};

function archPolicy(tag, coreTest, tags) {
  const inArch = (t) => (tags ? tags.includes(t) : t === tag);
  return (run, rnd) => {
    const offer = soloOfferFor(run);
    let best = null, bestScore = -1;
    for (let c = 0; c < 3; c++) {
      const id = offer[c], it = ITEMS[id];
      // merge anywhere is king
      const mslot = run.gear.findIndex((g) => g && g.id === id && g.rank < MAXRANK);
      if (mslot >= 0) { const sc = 100 + it.tier; if (sc > bestScore) { bestScore = sc; best = { choice: c, slot: mslot }; } continue; }
      let sc = it.tier * 2;
      if (inArch(it.tag) && !isCore(id)) sc += 6;
      if (isCore(id) && coreTest(it)) sc += 8;
      else if (isCore(id)) sc -= 4;
      const empty = run.gear.findIndex((g) => !g);
      if (empty >= 0) { if (sc > bestScore) { bestScore = sc; best = { choice: c, slot: empty } }; continue; }
      // replace the weakest off-archetype item
      let worst = -1, worstVal = 1e9;
      run.gear.forEach((g, i) => {
        if (!g) return;
        const gi = ITEMS[g.id];
        const keep = (inArch(gi.tag) && !isCore(g.id)) || (isCore(g.id) && coreTest(gi));
        const v = itemVal(gi, g.rank) + (keep ? 1000 : 0);
        if (v < worstVal) { worstVal = v; worst = i; }
      });
      sc -= 3;
      if (sc > bestScore && worst >= 0) { bestScore = sc; best = { choice: c, slot: worst }; }
    }
    return bestScore >= 4 ? best : { choice: -1, slot: 0 };
  };
}
policies["arch:blade"] = archPolicy(0, (it) => it.ctag === 0 || it.call);
policies["arch:bolt"] = archPolicy(1, (it) => it.ctag === 1 || it.call);
policies["arch:spark"] = archPolicy(2, (it) => it.ctag === 2 || it.call);
policies["arch:ember"] = archPolicy(3, (it) => it.cburn || it.call);
policies["arch:turtle"] = archPolicy(4, (it) => it.ctag === 4 || it.ctag === 5 || it.chp, [4, 5]);   // PLATE+MEND

policies["arch:blade:nocore"] = (run, rnd) => {          // CORE-ablated synergy bot (the real buff-economy probe)
  const base = archPolicy(0, () => false)(run, rnd);
  if (base.choice >= 0 && isCore(soloOfferFor(run)[base.choice])) return { choice: -1, slot: 0 };
  return base;
};

// search: enumerate the JOINT two picks before the fight, score by simulating the true combat
function actions(run) {
  const offer = soloOfferFor(run);
  const acts = [{ choice: -1, slot: 0 }];
  if (!offer) return acts;
  for (let c = 0; c < 3; c++) for (let s = 0; s < SLOTS; s++) acts.push({ choice: c, slot: s });
  return acts;
}
function buildPower(run) {
  return run.gear.reduce((t, g) => t + (g ? itemVal(ITEMS[g.id], g.rank) : 0), 0) + run.maxhp / 4;
}
function fightScore(run) {
  const enemy = enemyBuild(run.seed, run.stage);
  const c = simulateBuilds({ gear: run.gear, maxhp: run.maxhp }, enemy);
  const win = c.result === 1 || c.result === 3;
  // win margin decides the fight; buildPower breaks ties toward long-run growth (merge investment)
  return (win ? 1e6 + c.hp[0] : (enemy.maxhp - c.hp[1])) + buildPower(run) * 2;
}
policies.search = (run) => {
  let best = null, bestScore = -Infinity;
  for (const a1 of actions(run)) {
    const r1 = structuredClone(run);
    if (!soloPick(r1, a1.choice, a1.slot)) continue;
    for (const a2 of actions(r1)) {
      const r2 = structuredClone(r1);
      if (!soloPick(r2, a2.choice, a2.slot)) continue;
      const sc = fightScore(r2);
      if (sc > bestScore) { bestScore = sc; best = a1; }
    }
  }
  return best || { choice: -1, slot: 0 };
};

// no-CORE ablation: the search bot, forbidden from ever equipping a CORE item
policies["search:nocore"] = (run) => {
  let best = null, bestScore = -Infinity;
  const offer0 = soloOfferFor(run);
  const ok = (a, off) => a.choice === -1 || !isCore(off[a.choice]);
  for (const a1 of actions(run)) {
    if (!ok(a1, offer0)) continue;
    const r1 = structuredClone(run);
    if (!soloPick(r1, a1.choice, a1.slot)) continue;
    const offer1 = soloOfferFor(r1) || offer0;
    for (const a2 of actions(r1)) {
      if (!ok(a2, offer1)) continue;
      const r2 = structuredClone(r1);
      if (!soloPick(r2, a2.choice, a2.slot)) continue;
      const sc = fightScore(r2);
      if (sc > bestScore) { bestScore = sc; best = a1; }
    }
  }
  return best || { choice: -1, slot: 0 };
};

// ---- runner --------------------------------------------------------------------------------------------
function playRun(policyName, seed, rndSeed) {
  const pol = policies[policyName];
  const run = soloNew(seed);
  const rnd = prng(rndSeed);
  const stageAttempts = {};                              // stage -> attempts (for winrate curves)
  let guard = 0;
  while (!run.over && guard++ < 400) {
    while (run.picks > 0 && !run.over) {
      const a = pol(run, rnd) || { choice: -1, slot: 0 };
      if (!soloPick(run, a.choice, a.slot)) soloPick(run, -1, 0);
    }
    stageAttempts[run.stage] = (stageAttempts[run.stage] || 0) + 1;
    soloFight(run);
  }
  return { score: run.score, stageAttempts, gear: run.gear, maxhp: run.maxhp };
}
const q = (arr, p) => arr.slice().sort((a, b) => a - b)[Math.min(arr.length - 1, Math.floor(p * arr.length))];

const results = {};
for (const name of Object.keys(policies)) {
  const t0 = Date.now();
  const scores = [], stageWins = {}, stageTries = {};
  for (let i = 0; i < RUNS; i++) {
    const r = playRun(name, "lab-" + i, 7919 * i + 13);
    scores.push(r.score);
    for (const [st, tries] of Object.entries(r.stageAttempts)) {
      stageTries[st] = (stageTries[st] || 0) + tries;
      if (r.score >= Number(st)) stageWins[st] = (stageWins[st] || 0) + 1;
    }
  }
  results[name] = { scores, stageWins, stageTries, ms: Date.now() - t0 };
  console.log(`${name.padEnd(14)} median ${q(scores, 0.5)}  p90 ${q(scores, 0.9)}  max ${Math.max(...scores)}  mean ${(scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1)}  (${results[name].ms}ms)`);
}

// per-stage clear rate for the search bot (the brick-wall detector)
const s = results.search;
console.log("\nsearch bot — stage clear rates (of runs reaching the stage):");
let reached = RUNS;
for (let st = 1; st <= 30 && reached > 2; st++) {
  const wins = s.scores.filter((x) => x >= st).length;
  console.log(`  stage ${String(st).padStart(2)}: reached ${String(reached).padStart(3)}  cleared ${String(wins).padStart(3)}  (${(100 * wins / reached).toFixed(0)}%)`);
  reached = wins;
}
const bestPol = Object.keys(results).filter((n) => n !== "random" && n !== "hpstack")
  .sort((a, b) => q(results[b].scores, 0.5) - q(results[a].scores, 0.5))[0];
const depth = q(results[bestPol].scores, 0.5) / Math.max(1, q(results.random.scores, 0.5));
const depth90 = q(results[bestPol].scores, 0.9) / Math.max(1, q(results.random.scores, 0.9));
console.log(`\nDEPTH (best policy ${bestPol} vs random): median ${depth.toFixed(1)}x  p90 ${depth90.toFixed(1)}x`);
console.log(`CORE ablation (arch:blade vs arch:blade:nocore medians): ${q(results["arch:blade"].scores, 0.5)} vs ${q(results["arch:blade:nocore"].scores, 0.5)}  (p90 ${q(results["arch:blade"].scores, 0.9)} vs ${q(results["arch:blade:nocore"].scores, 0.9)})`);
console.log(`search:nocore median (search-side ablation): ${q(results["search:nocore"].scores, 0.5)}`);
const arch = ["arch:blade", "arch:bolt", "arch:spark", "arch:ember", "arch:turtle"].map((n) => q(results[n].scores, 0.5));
console.log(`archetype medians (blade/bolt/spark/ember/turtle): ${arch.join(" / ")}`);
console.log(`hpstack median (degenerate check): ${q(results.hpstack.scores, 0.5)}`);
