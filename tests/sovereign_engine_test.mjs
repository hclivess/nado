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
  // build most of the open land away so colonize is allowed
  settle(n, 20); n.money = 1e7;
  for (let i = 0; i < 3; i++) build(n, "village", buildsPerTurn(n));
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

console.log(fails ? fails + " FAILURES" : "ALL PASS");
process.exit(fails ? 1 : 0);
