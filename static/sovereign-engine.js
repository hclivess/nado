// sovereign-engine.js — the deterministic rules engine for NADO Sovereign, an original persistent-world
// NATION-WAR MMO in the classic Czech browser-strategy genre (a clean-room homage to Webgame.cz —
// mechanics only; every name, label, number layout and line of code here is original, game mechanics are
// not copyrightable). Pure and headless-testable (browser + node): a nation is a plain object, and every
// action is a pure state transition, so the on-chain contract and the offline practice mode share ONE set
// of rules and both re-derive byte-identical worlds.
//
// The heart is TIME. This is a turn-based economy with NO background process — production is computed
// LAZILY: `settle(n, turns)` advances a nation by however many turns elapsed since its last touch (the L1
// block cursor supplies `turns` on-chain). A nation nobody has read still "produced": its resources are
// whatever settle() would compute from the elapsed turns. Combat is a pure function of two settled nations
// plus one block-hash roll, so a raid is as provable as any move in our duel games.

// ---- resources ----------------------------------------------------------------------------------------
// Four stocks. 32-bit caps mirror the genre (a nation's treasury tops out at 2^32-1).
export const CAP = 4294967295;
export const RES = ["people", "money", "food", "energy"];

// ---- buildings (per-km² territory is one building slot) -----------------------------------------------
// eff() reads are applied in production(); `dens` multiplies the km²'s population, `hi`/`lo` set energy draw.
export const B = {
  unbuilt:   { k: "unbuilt",   dens: 1, txt: "Open land — settlers, and more to trade." },
  village:   { k: "village",   dens: 2, food: 1.5, money: 5, lo: 1, txt: "Doubles local people; +food, +money." },
  city:      { k: "city",      dens: 3, hi: 1, txt: "Triples local people." },
  market:    { k: "market",    tax: 3, hi: 1, txt: "Triples the tax money of its land." },
  farm:      { k: "farm",      food: 2, lo: 1, txt: "Grows food." },
  lab:       { k: "lab",       tech: 0.08, hi: 1, txt: "Researches technology." },
  factory:   { k: "factory",   comp: 1, hi: 1, txt: "Builds components for machine units." },
  barracks:  { k: "barracks",  troop: 0.3, lo: 1, txt: "Trains soldiers, no tech needed." },
  plant:     { k: "plant",     mwh: 2, txt: "Generates energy." },
  arena:     { k: "arena",     joy: 1, lo: 1, txt: "Entertainment — raises satisfaction." },
  base:      { k: "base",      mil: 1, lo: 1, txt: "Military base — strengthens the whole army." },
  builder:   { k: "builder",   build: 1, lo: 1, txt: "Construction firm — more builds per turn." },
  ruin:      { k: "ruin",      txt: "Rubble — rebuildable, produces nothing." },
};
export const BKEYS = Object.keys(B);
export const BUILDABLE = ["village", "city", "market", "farm", "lab", "factory", "barracks", "plant", "arena", "base", "builder"];

// ---- governments (multiplicative bonuses; original names, faithful effects) ----------------------------
// m=money f=food e=energy t=tech fac=factory bar=barracks atk=attack strength; day = earliest day available.
export const GOV = {
  anarchy:  { k: "anarchy",  atk: 0.80, fac: 0.75, food: 1.20, colonize: 1.20, txt: "No state. Cheap land, feeble armies." },
  feudal:   { k: "feudal",   txt: "Feudal order — rewards a lopsided, specialised realm." },
  dictator: { k: "dictator", bar: 1.10, t: 0.80, atk: 1.10, txt: "Iron fist — strong barracks and armies, weak science." },
  zealot:   { k: "zealot",   bar: 1.20, e: 1.008, m: 1.0, t: 0.75, salvo: 0.80, txt: "Zealotry — fervent troops, backward labs." },
  commune:  { k: "commune",  fac: 1.15, bar: 1.10, e: 1.20, m: 0.75, txt: "Collective — mighty industry, poor treasury." },
  technoc:  { k: "technoc",  t: 1.20, food: 0.90, atk: 0.90, txt: "Technocracy — science over soldiers." },
  democ:    { k: "democ",    t: 1.10, joy: 1.3, txt: "Democracy — balanced, content, tech-friendly." },
  republic: { k: "republic", fac: 1.20, m: 1.20, atk: 0.95, txt: "Republic — booming factories and coin." },
  utopia:   { k: "utopia",   fac: 1.25, bar: 1.25, e: 1.25, food: 1.25, t: 1.25, joy: 1.10, atk: 0.90, colonize: 1.3, txt: "Utopia — everything flourishes, but war withers." },
  robocr:   { k: "robocr",   fac: 1.35, e: 1.20, t: 1.20, food: 0.70, pop: 0.70, robots: 1, day: 25, txt: "Robocracy — robots run on power, not bread." },
};
export const GKEYS = Object.keys(GOV);

// ---- military units (attack/defense/salary/prestige; original names) ----------------------------------
export const U = {
  soldier: { k: "soldier", a: 1, d: 1, pay: 0.06, pres: 1,   src: "barracks", txt: "Trained in barracks — the backbone." },
  tank:    { k: "tank",    a: 6, d: 4, pay: 0.42, pres: 5,   src: "factory",  txt: "Heavy armour — attack and defend." },
  fighter: { k: "fighter", a: 6, d: 0, pay: 0.32, pres: 3.5, src: "factory",  txt: "All offense, no ground defense." },
  bunker:  { k: "bunker",  a: 0, d: 6, pay: 0.35, pres: 3.5, src: "factory",  txt: "A wall — pure defense." },
  mech:    { k: "mech",    a: 2, d: 3, pay: 0.20, pres: 2.7, src: "factory",  txt: "Runs on energy; self-repairs, −20% losses." },
  agent:   { k: "agent",   a: 0, d: 0, pay: 5,    pres: 15,  src: "market",   txt: "Spy — runs covert operations only." },
};
export const UKEYS = Object.keys(U);
export const FIGHT_UNITS = ["soldier", "tank", "fighter", "bunker", "mech"];   // agents don't join battles

// ---- technologies (each level is a multiplier; original names, faithful axes) -------------------------
export const TECH = {
  weapons: { k: "weapons", per: 0.04, cap: 10, axis: "atk",    txt: "Weapon Systems — army strength." },
  agri:    { k: "agri",    per: 0.04, cap: 10, axis: "food",   txt: "Agronomy — food output." },
  power:   { k: "power",   per: 0.04, cap: 10, axis: "energy", txt: "Grid Science — energy output." },
  trade:   { k: "trade",   per: 0.04, cap: 10, axis: "money",  txt: "Commerce — money output." },
  density: { k: "density", per: 0.04, cap: 10, axis: "dens",   txt: "Housing — people per km²." },
};
export const TKEYS = Object.keys(TECH);
export const TECH_COST = (level) => Math.round(50 * Math.pow(1.6, level));   // tech points to reach next level

export const ATTACK_KINDS = {
  conquest:    { k: "conquest",    land: [2, 16], loot: [1, 8],   txt: "Conquest — seize land and a little plunder." },
  plunder:     { k: "plunder",     land: [1, 8],  loot: [2, 16],  txt: "Plunder — grab goods, some land." },
  annihilate:  { k: "annihilate",  land: [0, 0],  loot: [2, 12],  raze: 1, txt: "Annihilation — raze buildings and stockpiles." },
};

// ---- deterministic hashing (shared with the contract's beacon rolls) ----------------------------------
import { blake2bHash } from "./nadotx.js";
const H = (v) => BigInt("0x" + blake2bHash(v));
// roll(seed, i) -> a float in [0,1); seed is the block-hash-derived BigInt the contract also uses.
export const roll = (seed, i) => Number(H((seed % (1n << 200n)).toString(16) + ":" + i) % 1000000n) / 1000000;

// ---- a fresh nation -----------------------------------------------------------------------------------
export const START_LAND = 40;
export function newNation(owner, day = 0) {
  const bld = {}; for (const k of BKEYS) bld[k] = 0;
  bld.unbuilt = START_LAND;
  const units = {}; for (const k of UKEYS) units[k] = 0;
  const tech = {}; for (const k of TKEYS) tech[k] = 0;
  return {
    owner, day, land: START_LAND, bld, units, tech,
    people: 8000, money: 5000, food: 2000, energy: 1000,
    techPts: 0, comps: 0, gov: "feudal", joy: 60,            // joy = satisfaction %
    ready: 100, morale: 50, exp: 0, prestige: 0, ally: 0,
    tick: 0,                                                  // turns elapsed at last settle (the lazy clock)
    over: false,
  };
}

// ---- helpers ------------------------------------------------------------------------------------------
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const g = (n) => GOV[n.gov] || GOV.feudal;
const techMul = (n, axis) => 1 + TKEYS.reduce((s, k) => s + (TECH[k].axis === axis ? n.tech[k] * TECH[k].per : 0), 0);
// satisfaction multipliers: each point above/below 50 shifts output (money .75%/pt, tech/mil .5%/pt).
const joyMul = (n, rate) => 1 + (n.joy - 50) * rate / 100;

// population capacity from land + building density + housing tech
export function capacity(n) {
  let slots = 0;
  for (const k of BKEYS) slots += n.bld[k] * (B[k].dens || 1);
  return Math.floor(350 * slots * techMul(n, "dens") * (g(n).pop || 1));
}

// ---- production: the net per-turn deltas AFTER all bonuses (people/money/food/energy/tech/troops) -----
export function production(n) {
  const gov = g(n), joyM = joyMul(n, 0.75), robots = !!gov.robots;
  // money: every person earns; markets triple their land's tax; trade tech, gov, satisfaction stack
  let money = n.people * 0.0125;
  for (const k of BKEYS) if (B[k].money) money += n.bld[k] * B[k].money;
  money *= (1 + (n.bld.market * 2) / Math.max(1, n.land)) * techMul(n, "money") * (gov.m || 1) * joyM;
  // food
  let food = 0; for (const k of BKEYS) if (B[k].food) food += n.bld[k] * B[k].food;
  food *= techMul(n, "food") * (gov.food || 1);
  const eatPeople = n.people / 1000 * 0.25;
  const nonMech = UKEYS.reduce((s, k) => k === "mech" ? s : s + n.units[k], 0);
  const eatUnits = robots ? 0 : nonMech / 1000 * 5;
  food -= eatPeople + eatUnits;
  // energy
  let mwh = 0; for (const k of BKEYS) if (B[k].mwh) mwh += n.bld[k] * B[k].mwh;
  mwh *= techMul(n, "energy") * (gov.e || 1);
  for (const k of BKEYS) mwh -= n.bld[k] * (B[k].hi ? 0.2 : B[k].lo ? 0.1 : 0);
  const totTech = TKEYS.reduce((s, k) => s + n.tech[k], 0);
  mwh -= totTech / 1000 * 5 + (robots ? n.units.mech / 1000 * 5 : 0);
  // tech points + components + soldiers
  let tech = 0; for (const k of BKEYS) if (B[k].tech) tech += n.bld[k] * B[k].tech;
  tech *= joyMul(n, 0.5) * (gov.t || 1);
  const comps = n.bld.factory * (B.factory.comp) * (gov.fac || 1);
  const troops = n.bld.barracks * B.barracks.troop * (gov.bar || 1);
  // people growth: toward capacity, scaled by satisfaction (content nations breed faster)
  const cap = capacity(n);
  const grow = Math.max(0, cap - n.people) * 0.02 * clamp(n.joy / 60, 0.2, 1.6);
  return { money, food, energy: mwh, tech, comps, troops, grow, cap };
}

// per-turn salary bill (money) for the standing army
export function upkeep(n) { return UKEYS.reduce((s, k) => s + n.units[k] * U[k].pay, 0); }

// ---- settle: advance a nation by `turns` whole turns (the lazy production clock) -----------------------
// Deterministic and idempotent given (nation, turns). Starvation/blackout bite when a stock hits zero.
export function settle(n, turns) {
  turns = Math.max(0, Math.floor(turns));
  if (!turns || n.over) { n.tick += turns; return n; }
  for (let t = 0; t < turns && !n.over; t++) {
    const p = production(n), pay = upkeep(n);
    n.money = clamp(n.money + p.money - pay, 0, CAP);
    n.food = clamp(n.food + p.food, 0, CAP);
    n.energy = clamp(n.energy + p.energy, 0, CAP);
    n.techPts += p.tech;
    n.comps += p.comps;
    // train soldiers if barracks output and money allow (auto — the genre trains passively)
    n.units.soldier += Math.floor(p.troops);
    // population: grow toward capacity; STARVE if food ran dry (people leave/die)
    if (n.food <= 0) n.people = Math.max(0, Math.floor(n.people * 0.97));
    else n.people = clamp(Math.floor(n.people + p.grow), 0, capacity(n));
    // satisfaction drifts toward a target set by arenas, size penalty, government joy bonus
    const target = clamp(50 + n.bld.arena * 0.5 * (g(n).joy || 1) - n.land / 2000, 5, 100);
    n.joy = clamp(n.joy + (target - n.joy) * 0.25, 0, 100);
    // army readiness recovers over time
    n.ready = clamp(n.ready + 4, 0, 100);
  }
  n.tick += turns;
  return n;
}

// ---- actions (pure transitions; return true on success, false on illegal — the contract mirrors these) -
export function buildsPerTurn(n) { return Math.floor(12 + n.bld.builder / 6); }
export function buildCost(n, count) {          // total money for `count` new buildings (rising unit cost)
  const start = totalBuilt(n); let c = 0;
  for (let i = 0; i < count; i++) c += 300 + (start + i) * 0.3;
  return Math.round(c);
}
const totalBuilt = (n) => BUILDABLE.reduce((s, k) => s + n.bld[k], 0) + n.bld.ruin;

export function build(n, type, count) {
  if (!BUILDABLE.includes(type) || count <= 0) return false;
  if (count > buildsPerTurn(n)) return false;               // one turn's worth of construction
  if (n.bld.unbuilt < count) return false;                  // must have open land
  const cost = buildCost(n, count);
  if (n.money < cost) return false;
  n.money -= cost; n.bld.unbuilt -= count; n.bld[type] += count;
  return true;
}
export function demolish(n, type, count) {
  if (!BKEYS.includes(type) || type === "unbuilt" || count <= 0 || n.bld[type] < count) return false;
  const cost = Math.round(buildCost(n, count) / 10);
  if (n.money < cost) return false;
  n.money -= cost; n.bld[type] -= count; n.bld.unbuilt += count;
  return true;
}
export function colonize(n) {
  if (n.bld.unbuilt / Math.max(1, n.land) > 0.5) return false;   // can't hoard empty land
  const found = Math.max(6, Math.floor(30 * Math.pow(0.9997, n.land)) * (g(n).colonize || 1));
  n.land += found; n.bld.unbuilt += found; return found;
}
export function recruit(n, unit, count) {
  const u = U[unit]; if (!u || count <= 0) return false;
  if (unit === "soldier") return false;                     // soldiers come only from barracks (passive)
  if (unit === "mech" || unit === "tank" || unit === "fighter" || unit === "bunker") {
    if (n.comps < count) return false;                      // machine units need components
    const cost = count * u.pay * 20;                        // buy-in ~ 20 turns of pay
    if (n.money < cost) return false;
    n.comps -= count; n.money -= cost; n.units[unit] += count; return true;
  }
  // agent: bought on the market with money only
  const cost = count * u.pay * 30;
  if (n.money < cost) return false;
  n.money -= cost; n.units.agent += count; return true;
}
export function research(n, tech) {
  const tk = TECH[tech]; if (!tk || n.tech[tech] >= tk.cap) return false;
  const cost = TECH_COST(n.tech[tech]);
  if (n.techPts < cost) return false;
  n.techPts -= cost; n.tech[tech] += 1; return true;
}
export function revolt(n, gov) {
  const gv = GOV[gov]; if (!gv || gov === n.gov) return false;
  if ((gv.day || 0) > n.day) return false;                  // some governments unlock later
  const to = gov === "robocr" ? 0.20 : 0.12, bl = gov === "robocr" ? 0.16 : 0.08;
  const from = n.gov === "anarchy";                          // anarchy revolts painlessly
  if (!from) {
    for (const k of ["money", "food", "energy", "people"]) n[k] = Math.floor(n[k] * (1 - to));
    for (const k of UKEYS) n.units[k] = Math.floor(n.units[k] * (1 - to));
    for (const k of BKEYS) if (k !== "unbuilt") n.bld[k] = Math.floor(n.bld[k] * (1 - bl));
  }
  n.gov = gov; n.ready = Math.min(n.ready, 40); return true;
}

// ---- army strength -----------------------------------------------------------------------------------
// side="atk"|"def"; comp = {unit: fraction 0..1} for a normal attack (defaults to whole army on defense).
export function power(n, side, comp) {
  const gov = g(n), wm = techMul(n, "atk"), baseM = 1 + n.bld.base / Math.max(1, n.land) * 0.2;
  const joyM = joyMul(n, 0.5), readyM = 0.4 + 0.6 * (n.ready / 100), expM = 1 + clamp(n.exp / 1000, 0, 0.45);
  let s = 0;
  for (const k of FIGHT_UNITS) {
    const q = comp ? Math.floor(n.units[k] * (comp[k] || 0)) : n.units[k];
    s += q * (side === "atk" ? U[k].a : U[k].d);
  }
  if (side === "def" && n.gov === "anarchy") s += Math.floor(n.people / 100);   // anarchy: people defend
  return s * wm * baseM * joyM * readyM * expM * (gov.atk || 1);
}

// ---- combat: pure resolution of one raid; mutates BOTH nations, returns a report -----------------------
// atk/def already settled to the same turn. kind in ATTACK_KINDS; comp = attacker composition fractions.
// seed = block-hash-derived roll source (the contract passes the same). Returns { win, log fields }.
export function combat(atk, def, kind, comp, seed) {
  const K = ATTACK_KINDS[kind]; if (!K) return { ok: false };
  const ap = power(atk, "atk", comp), dp = power(def, "def", null);
  const swing = 0.85 + 0.3 * roll(seed, 0);                 // ±15% luck
  const win = ap * swing > dp;
  const rep = { ok: true, kind, win, ap: Math.round(ap), dp: Math.round(dp), lootLand: 0, loot: {}, razed: 0, defLoss: {}, atkLoss: {} };
  // casualties: proportional to the clash, the loser bleeds more; mechs lose 20% less
  const fierce = kind === "annihilate" ? 0.5 : kind === "conquest" ? 0.4 : 0.35;
  const bleed = (nn, base) => { for (const k of FIGHT_UNITS) {
    let r = base * (0.6 + 0.8 * roll(seed, k.length + (nn === atk ? 1 : 2)));
    if (k === "mech") r *= 0.8;
    const lost = Math.floor(nn.units[k] * clamp(r, 0, 0.9)); nn.units[k] -= lost;
    (nn === atk ? rep.atkLoss : rep.defLoss)[k] = lost;
  } };
  bleed(atk, fierce * (win ? 0.6 : 1.0));
  bleed(def, fierce * (win ? 1.0 : 0.5));
  atk.ready = clamp(atk.ready - 30, 0, 100);
  if (win) {
    const band = (b, i) => (b[0] + (b[1] - b[0]) * roll(seed, 100 + i)) / 100;
    if (K.land[1]) { const take = Math.floor(def.land * band(K.land, 1)); rep.lootLand = take;
      def.land -= take; atk.land += take;
      // move mostly-open land: strip the defender's unbuilt first, then rubble the rest onto the attacker
      const fromUnbuilt = Math.min(def.bld.unbuilt, take); def.bld.unbuilt -= fromUnbuilt;
      atk.bld.unbuilt += take; }
    if (K.raze) {                                            // annihilation: destroy, don't take
      const r = band(K.loot, 2);
      for (const k of BUILDABLE) { const d = Math.floor(def.bld[k] * r); def.bld[k] -= d; def.bld.ruin += d; rep.razed += d; }
      for (const res of ["money", "food", "energy"]) { const d = Math.floor(def[res] * r); def[res] -= d; rep.loot[res] = -d; }
    } else {                                                 // conquest/plunder: steal goods
      const r = band(K.loot, 3);
      for (const res of ["money", "food", "energy"]) { const d = Math.floor(def[res] * r); def[res] -= d; atk[res] = clamp(atk[res] + d, 0, CAP); rep.loot[res] = d; }
    }
    def.joy = clamp(def.joy - (kind === "annihilate" ? 12 : 6), 0, 100);
    atk.exp += 20; atk.morale = clamp(atk.morale + 3, 0, 100);
    atk.prestige += 5; def.prestige = Math.max(0, def.prestige - 2);
  } else {
    atk.morale = clamp(atk.morale - 5, 0, 100);
    def.morale = clamp(def.morale + 2, 0, 100); def.exp += 8;
  }
  return rep;
}

// ---- prestige (the world-ranking score) --------------------------------------------------------------
export function prestige(n) {
  let s = n.land * 2 + Math.floor(n.people / 1000);
  for (const k of BUILDABLE) s += n.bld[k];
  for (const k of UKEYS) s += Math.floor(n.units[k] * U[k].pres);
  for (const k of TKEYS) s += n.tech[k] * 20;
  return Math.floor(s);
}
