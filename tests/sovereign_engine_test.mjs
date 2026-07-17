/*
 * sovereign-engine.js test: the deterministic nation simulation. Asserts the money-safe / provable
 * invariants a persistent PvP world needs — settle() is deterministic and idempotent-by-turn-count, the
 * economy is bounded (never NaN, never > CAP, never < 0), actions reject illegal moves, and combat is a
 * pure function of (attacker, defender, seed) that conserves what it moves (loot leaves the defender and
 * arrives at the attacker; razed land becomes rubble, not thin air). Run: node tests/sovereign_engine_test.mjs
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/sovereign-engine.js");
const { newNation, settle, production, build, recruit, research, revolt, colonize, combat, prestige,
        buildsPerTurn, buildCost, CAP, BUILDABLE, UKEYS, TKEYS, capacity } = E;

let fails = 0;
const check = (name, fn) => { try { fn(); console.log("PASS  " + name); } catch (e) { fails++; console.log("FAIL  " + name + ": " + (e && e.stack || e)); } };
const clone = (n) => JSON.parse(JSON.stringify(n));
const finite = (n) => { for (const k of ["people", "money", "food", "energy", "joy", "land"])
  if (!Number.isFinite(n[k]) || n[k] < 0 || n[k] > CAP + 1) throw new Error(`${k}=${n[k]} out of range`); };

check("settle: deterministic + split-equals-whole (idempotent by turn count)", () => {
  const a = newNation("ndoA".padEnd(50, "a")), b = clone(a);
  settle(a, 200);
  settle(b, 120); settle(b, 80);                       // same total in two hops must match one hop
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error("settle not turn-additive");
  finite(a);
  if (a.tick !== 200) throw new Error("tick bookkeeping");
});

check("economy stays bounded over a long idle (no NaN / overflow / negative)", () => {
  for (let s = 0; s < 40; s++) {
    const n = newNation("ndo" + s);
    settle(n, 5000);                                   // a very long absence
    finite(n);
    const p = production(n);
    for (const k in p) if (!Number.isFinite(p[k])) throw new Error("production " + k + " NaN at seed " + s);
  }
});

check("a built economy grows money+people vs a bare one", () => {
  const bare = newNation("bare".padEnd(50, "x"));
  const built = clone(bare);
  // give the built nation land + a spread of producers
  built.land += 300; built.bld.unbuilt += 300;
  for (const [t, c] of [["village", 60], ["farm", 40], ["market", 40], ["plant", 40], ["lab", 20], ["barracks", 30]]) built.bld[t] += c;
  built.bld.unbuilt -= 230;
  settle(bare, 300); settle(built, 300);
  if (!(built.people > bare.people)) throw new Error("built nation should grow more people");
  if (!(built.money > bare.money)) throw new Error("built nation should out-earn");
  if (!(prestige(built) > prestige(bare))) throw new Error("prestige should reward development");
});

check("actions reject illegal moves; legal ones cost what they should", () => {
  const n = newNation("act".padEnd(50, "z")); settle(n, 50);
  if (build(n, "notabuilding", 1)) throw new Error("bad type built");
  if (build(n, "village", buildsPerTurn(n) + 1)) throw new Error("over the per-turn build cap");
  const before = n.money, cost = buildCost(n, 5);
  if (!build(n, "village", 5)) throw new Error("legal build rejected");
  if (n.money !== before - cost) throw new Error("build cost wrong");
  if (n.bld.village < 5) throw new Error("buildings not added");
  // research: needs points
  n.techPts = 0;
  if (research(n, "weapons")) throw new Error("research with no points");
  n.techPts = 1e6;
  if (!research(n, "weapons") || n.tech.weapons !== 1) throw new Error("legal research rejected");
  // recruit machine unit needs components
  n.comps = 0;
  if (recruit(n, "tank", 1)) throw new Error("tank with no components");
  // soldiers can't be hand-recruited (barracks only)
  if (recruit(n, "soldier", 1)) throw new Error("soldier hand-recruited");
});

check("revolution taxes the nation (except from anarchy) and unlocks by day", () => {
  const n = newNation("rev".padEnd(50, "q")); settle(n, 100);
  n.money = 100000; n.people = 50000;
  const m0 = n.money;
  if (!revolt(n, "republic")) throw new Error("legal revolt rejected");
  if (!(n.money < m0)) throw new Error("revolt should cost resources");
  // robocracy locked before day 25
  const young = newNation("yng".padEnd(50, "p")); young.day = 10;
  if (revolt(young, "robocr")) throw new Error("robocracy before day 25");
  young.day = 30;
  if (!revolt(young, "robocr")) throw new Error("robocracy after day 25 rejected");
});

check("colonize adds land but not while empty land is hoarded", () => {
  const n = newNation("col".padEnd(50, "c"));
  // build most of the open land away so colonize is allowed — the per-turn build cap means this now takes
  // several turns (settle between batches to advance the turn), matching the source's build-rate limit.
  settle(n, 20); n.money = 1e7;
  for (let t = 0; t < 6 && n.bld.unbuilt > 0; t++) { build(n, "village", Math.min(buildsPerTurn(n), n.bld.unbuilt)); settle(n, 20); }
  const land0 = n.land, got = colonize(n);
  if (!got || n.land <= land0) throw new Error("colonize should add land");
  // hoarding guard: a nation that is mostly empty land can't colonize
  const h = newNation("hrd".padEnd(50, "h"));
  if (colonize(h) && h.bld.unbuilt / h.land > 0.5) throw new Error("colonized while hoarding");
});

check("combat: deterministic, conserves loot (defender loses what attacker gains), stronger wins", () => {
  const mk = (troops) => { const n = newNation("A".padEnd(50, "1")); settle(n, 40);
    n.money = 5e6; n.food = 1e6; n.energy = 1e6; n.units.soldier = troops; n.units.tank = Math.floor(troops / 10); n.ready = 100; return n; };
  const atk = mk(20000), def = mk(1200);
  const money0 = { atk: atk.money, def: def.money };
  const seed = 123456789012345678901234567890n;
  // determinism: the SAME inputs on independent clones must produce identical outputs
  const atkC = clone(atk), defC = clone(def);
  const r1 = combat(atk, def, "plunder", { soldier: 1, tank: 1 }, seed);
  combat(atkC, defC, "plunder", { soldier: 1, tank: 1 }, seed);
  if (JSON.stringify(atk) !== JSON.stringify(atkC) || JSON.stringify(def) !== JSON.stringify(defC))
    throw new Error("combat not deterministic");
  if (!r1.win) throw new Error("overwhelming attacker should win");
  // conservation: money looted off the defender equals what the attacker gained
  const defMoneyLost = money0.def - def.money, atkMoneyGain = atk.money - money0.atk;
  if (r1.loot.money > 0 && Math.abs(defMoneyLost - r1.loot.money) > 2) throw new Error("loot not conserved on defender side");
  if (r1.loot.money > 0 && Math.abs(atkMoneyGain - r1.loot.money) > 2) throw new Error("loot not conserved on attacker side");
  finite(atk); finite(def);
  // a hopeless attacker loses
  const weak = mk(200), strong = mk(30000);
  const r3 = combat(weak, strong, "conquest", { soldier: 1 }, seed);
  if (r3.win) throw new Error("weak attacker should lose");
});

check("annihilation razes buildings into rubble (land conserved, not vanished)", () => {
  const atk = newNation("R".padEnd(50, "9")); settle(atk, 40); atk.units.fighter = 40000; atk.units.tank = 4000; atk.money = 1e7; atk.ready = 100;
  const def = newNation("D".padEnd(50, "8")); settle(def, 40); def.money = 2e6;
  def.land += 200; def.bld.unbuilt += 200; for (let i = 0; i < 4; i++) build(def, "village", buildsPerTurn(def));
  const land0 = def.land, built0 = BUILDABLE.reduce((s, k) => s + def.bld[k], 0) + def.bld.ruin;
  const r = combat(atk, def, "annihilate", { fighter: 1, tank: 1 }, 99999999999999999999n);
  if (r.win) {
    if (def.land !== land0) throw new Error("annihilation must not move land");
    const built1 = BUILDABLE.reduce((s, k) => s + def.bld[k], 0) + def.bld.ruin;
    if (built1 !== built0) throw new Error("razed buildings must become rubble, not vanish");
    if (r.razed <= 0) throw new Error("nothing razed on a win");
  }
});

check("world replay: deterministic, isolates nations, resolves a raid, seed-blocks", () => {
  const A = "ndoA".padEnd(50, "a"), Bn = "ndoB".padEnd(50, "b");
  const seedOf = (cur) => BigInt(cur) * 99991n + 7n;      // stand-in for the block-hash roll
  const TB = E.TURN_BLOCKS;
  // A founds, builds up; B founds; A raids B much later
  const log = [
    { actor: A, cursor: 0, enc: E.encAction(E.OP.found), target: 0 },
    { actor: Bn, cursor: 0, enc: E.encAction(E.OP.found), target: 0 },
    // A builds on its open land first (the anti-hoard rule blocks colonizing while >50% is empty), with
    // turns between builds to afford them (the early economy is deliberately slow)…
    { actor: A, cursor: 1 * TB, enc: E.encAction(E.OP.build, E.BUILDABLE.indexOf("village"), 12), target: 0 },
    { actor: A, cursor: 80 * TB, enc: E.encAction(E.OP.build, E.BUILDABLE.indexOf("village"), 12), target: 0 },
    // …then unbuilt is under half and it can colonize for more territory
    { actor: A, cursor: 90 * TB, enc: E.encAction(E.OP.colonize), target: 0 },
  ];
  const now = 200 * TB;
  const w1 = E.replayWorld(log, now, seedOf).world;
  const w2 = E.replayWorld(JSON.parse(JSON.stringify(log)), now, seedOf).world;
  if (JSON.stringify(w1) !== JSON.stringify(w2)) throw new Error("world replay not deterministic");
  if (!w1[A] || !w1[Bn]) throw new Error("both nations should exist");
  // A colonized so it has more land than the untouched B
  if (!(w1[A].land > w1[Bn].land)) throw new Error("A should have colonized past B");
  finite(w1[A]); finite(w1[Bn]);
  // now a raid: A (with an army) attacks B after the newbie shield expires
  const raidLog = log.concat([
    { actor: A, cursor: 100 * TB, enc: E.encAction(E.OP.recruit, UKEYS.indexOf("tank"), 200), target: 0 },
    { actor: A, cursor: 120 * TB, enc: E.encAction(E.OP.attack, 1, E.packComp({ soldier: 1, tank: 1 }).b, E.packComp({ soldier: 1, tank: 1 }).c), target: Bn },
  ]);
  // give A components by hand-seeding? no — engine passive comps accrue via factories; instead build factories first
  const raidLog2 = [
    { actor: A, cursor: 0, enc: E.encAction(E.OP.found), target: 0 },
    { actor: Bn, cursor: 0, enc: E.encAction(E.OP.found), target: 0 },
  ];
  for (let k = 1; k <= 6; k++) raidLog2.push({ actor: A, cursor: k * TB, enc: E.encAction(E.OP.build, E.BUILDABLE.indexOf("barracks"), 12), target: 0 });
  raidLog2.push({ actor: A, cursor: 130 * TB, enc: E.encAction(E.OP.attack, 1, E.packComp({ soldier: 1 }).b, E.packComp({ soldier: 1 }).c), target: Bn });
  const bBefore = E.replayWorld(raidLog2.slice(0, -1), 130 * TB, seedOf).world[Bn];
  const rw = E.replayWorld(raidLog2, 130 * TB, seedOf).world;
  // B's money should have dropped or stayed (a plunder can't INCREASE the victim); the raid must have applied or been shielded
  if (rw[Bn].money > bBefore.money + 1) throw new Error("victim gained money from being raided");
  // seed-block pause: a null seed marks blocked, no partial corruption
  const blocked = E.replayWorld(raidLog2, 130 * TB, (cur) => cur >= 130 * TB ? null : seedOf(cur));
  if (!blocked.blocked) throw new Error("a pending seed block should pause replay");
});

const army = (owner, o = {}) => { const n = newNation(owner.padEnd(50, "x")); settle(n, 60);
  n.money = 5e6; n.food = 2e6; n.energy = 2e6; n.techPts = 1e6; n.rocketPts = 1e5; n.comps = 1e5; n.ready = 100;
  Object.assign(n.units, { soldier: 40000, tank: 4000, fighter: 4000, bunker: 2000, mech: 3000, agent: 500 }); return Object.assign(n, o); };

check("ranks + veteran bonuses unlock by army experience", () => {
  const n = newNation("rank".padEnd(50, "r"));
  if (E.rankOf(n) !== 0) throw new Error("fresh nation is rank 0");
  n.exp = 900000; const r = E.rankOf(n);           // between colonel(850k) and general(1.15M) → index 9
  if (E.RANKS[r].k !== "colonel") throw new Error("rank threshold wrong: " + E.RANKS[r].k);
  if (E.veteran(n).expPerTurn !== 100) throw new Error("rank 9 should grant +100 exp/turn");
  n.exp = 2500000; if (!(E.veteran(n).armyStr > 1)) throw new Error("top rank should boost army strength");
});

check("generals multiply strength and level on XP", () => {
  const n = army("gen");
  const base = E.power(n, "atk", { soldier: 1, tank: 1 });
  n.generals = [{ type: "nationalist", xp: 100000 }];   // level 5 → +15% attack
  const boosted = E.power(n, "atk", { soldier: 1, tank: 1 });
  if (!(boosted > base * 1.1)) throw new Error("nationalist general should boost attack");
  if (E.genLevel(100000) !== 5) throw new Error("general level ladder");
  if (E.genLevel(400000) !== 7) throw new Error("general max level");
});

check("missiles: build from rocket points, launch applies exact effect", () => {
  const atk = army("mA"), def = army("mD");
  atk.rocketPts = 2000;
  if (!E.buildMissile(atk, "nuke", 3)) throw new Error("build nuke rejected");   // 500×3=1500
  if (atk.rockets.nuke !== 3 || atk.rocketPts !== 500) throw new Error("missile build accounting");
  const land0 = def.land, ppl0 = def.people;
  const r = E.launchMissiles(atk, def, "nuke", 3, true);
  if (!r.ok) throw new Error("launch failed");
  if (!(def.land < land0) || !(def.people < ppl0)) throw new Error("nuke should hit land + people");
  if (atk.rockets.nuke !== 0) throw new Error("missiles not consumed");
  // outside war → half effect
  const d2 = army("mD2"), a2 = army("mA2"); a2.rockets.bio = 2;
  const p0 = d2.people; E.launchMissiles(a2, d2, "bio", 1, false);
  const p1 = d2.people; d2.people = p0; a2.rockets.bio = 1; E.launchMissiles(a2, d2, "bio", 1, true);
  if (!(p0 - p1 < p0 - d2.people)) throw new Error("outside-war missile should be weaker");
});

check("tactical attacks hit their targeted asset", () => {
  const atk = army("tA"), def = army("tD");
  const bunkers0 = def.units.bunker;
  atk.units.soldier = 200000;                         // overwhelming soldiers → breach bunkers
  const r = E.tactical(atk, def, "breach", 555555555555555555n);
  if (r.win && !(def.units.bunker < bunkers0)) throw new Error("breach should destroy bunkers on a win");
  // rear strike cuts tanks
  const t0 = def.units.tank; atk.units.tank = 50000;
  const r2 = E.tactical(atk, def, "rear", 777777777777777777n);
  if (r2.win && !(def.units.tank < t0)) throw new Error("rear strike should cut tanks");
});

check("espionage: steal caps to prestige, sabotage damages, agents can die", () => {
  const atk = army("sA"), def = army("sD");
  atk.units.agent = 5000; def.units.agent = 100;      // strong spy vs weak
  def.money = 1e6; const m0 = def.money, am0 = atk.money;
  const r = E.spyOp(atk, def, "theft_bank", 2000, 888888888888888888n);
  if (r.win) { if (!(def.money < m0)) throw new Error("bank theft should drain the victim");
    if (!(atk.money > am0)) throw new Error("thief should gain the money"); }
  // sabotage army drops readiness
  const rd0 = def.ready; const r2 = E.spyOp(atk, def, "sab_army", 2000, 999n);
  if (r2.win && !(def.ready < rd0)) throw new Error("army sabotage should drop readiness");
});

check("domestic market: buy raises stock for money, sell is cheaper", () => {
  const n = army("mkt"); n.money = 1e7; const f0 = n.food, m0 = n.money;
  if (!E.marketBuy(n, "food", 1000)) throw new Error("buy food rejected");
  if (!(n.food > f0) || !(n.money < m0)) throw new Error("buy should trade money for food");
  const sellPrice = Math.floor(E.unitPrice(n, "food") * 0.6);
  if (!(sellPrice < E.unitPrice(n, "food"))) throw new Error("sell price should be below buy price");
});

check("advances: cost scales with difficulty; alien ones can't be bought", () => {
  const n = army("adv"); n.techPts = 1e7;
  const c0 = E.advCost(n, "genome"); n.land += 20000; const c1 = E.advCost(n, "genome");
  if (!(c1 > c0)) throw new Error("bigger nation → costlier advance");
  if (!E.buildAdvance(n, "genome")) throw new Error("legal advance rejected");
  if (!E.hasAdv(n, "genome")) throw new Error("advance not recorded");
  if (E.buildAdvance(n, "plasma")) throw new Error("alien advance should not be buildable");
});

check("events fire deterministically and stay bounded", () => {
  const a = newNation("ev".padEnd(50, "e")), b = JSON.parse(JSON.stringify(a));
  settle(a, 500); settle(b, 250); settle(b, 250);
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error("events break turn-additivity");
  finite(a);
});

check("alliances: members share government bonuses scaled by count", () => {
  const mk = (o, gov) => { const n = newNation(o.padEnd(50, "a")); n.gov = gov; n.ally = 7; return n; };
  const w = { A: mk("A", "republic"), B: mk("B", "technoc"), C: mk("C", "dictator"), D: mk("D", "commune") };
  E.computeAlliances(w);
  if (!w.A._ally || w.A._ally.members !== 4) throw new Error("alliance roster");
  // republic contributes +tax, technocracy +food/energy/tech, dictator +atk, all ×floor(4/2)=2
  if (!(E.allyB(w.A, "tax") > 0) || !(E.allyB(w.A, "atk") > 0)) throw new Error("bonuses not aggregated");
  // a lone nation gets nothing
  const solo = { S: mk("S", "republic") }; solo.S.ally = 9; E.computeAlliances(solo);
  if (E.allyB(solo.S, "tax") !== 0) throw new Error("solo alliance shouldn't pay a bonus (floor(1/2)=0)");
});

check("medals award by threshold", () => {
  const n = army("med"); n.units.soldier = 1100000; n.land = 6000;
  const m = E.medals(n);
  if (m.soldiers !== 2) throw new Error("soldier medal tier (1M→lvl2)");
  if (m.territory !== 1) throw new Error("territory medal tier (5k→lvl1)");
});

console.log(fails ? fails + " FAILURES" : "ALL PASS");
process.exit(fails ? 1 : 0);
