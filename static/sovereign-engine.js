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

// ---- tactical attacks (6, single unit type; allies don't help; exact source effects) ------------------
export const TACTICAL = {
  partisan:  { k: "partisan",  unit: "soldier", def: ["soldier", "agent"], ready: 5,  hit: "energy",  band: [6, 16], txt: "Partisans — burn 6–16% of enemy energy, −5% readiness." },
  breach:    { k: "breach",    unit: "soldier", def: ["soldier"],          ready: 0,  hit: "bunker",   scale: 1,       txt: "Bunker breach — soldiers destroy bunkers by superiority." },
  rear:      { k: "rear",      unit: "tank",    def: ["tank"],             ready: 9,  hit: "tank",     band: [0, 10],  txt: "Rear strike — cut up to 10% of enemy tanks, −9% readiness." },
  bombing:   { k: "bombing",   unit: "fighter", def: ["fighter", "bunker"], ready: 10, hit: "building", band: [0, 4],  pop: [0, 10], txt: "City bombing — raze up to 4% of buildings, 10% people, −10% readiness." },
  airraid:   { k: "airraid",   unit: "fighter", def: ["fighter", "bunker"], ready: 5,  hit: "base",     band: [0, 10],  txt: "Tactical air raid — wreck up to 10% of military bases, −5% readiness." },
  nightraid: { k: "nightraid", unit: "mech",    def: ["mech"],             ready: 0,  hit: "baseunit", band: [0, 12],  txt: "Night raid — destroy up to 12% of bases and units." },
};
export const TKEYS_TAC = Object.keys(TACTICAL);

// ---- generals (9 types; per-level bonus, capped; XP ladder) -------------------------------------------
export const GENERALS = {
  nationalist: { k: "nationalist", per: 3, max: 24, axis: "atk",      txt: "+3% attack strength / level." },
  patriot:     { k: "patriot",     per: 4, max: 32, axis: "def",      txt: "+4% defense strength / level." },
  liberator:   { k: "liberator",   per: 5, max: 40, axis: "vsBig",    txt: "+5% attack vs more prestigious foes / level." },
  strategist:  { k: "strategist",  per: 5, max: 40, axis: "tacAtk",   txt: "+5% tactical attack / level." },
  protector:   { k: "protector",   per: 5, max: 40, axis: "tacDef",   txt: "+5% tactical defense / level." },
  spy:         { k: "spy",         per: 5, max: 70, axis: "spy",      txt: "+5% espionage, −5% agent losses / level." },
  economist:   { k: "economist",   per: -5, max: -70, axis: "wage",   txt: "−5% salary costs / level." },
  conqueror:   { k: "conqueror",   per: 5, max: 40, axis: "loot",     txt: "+5% conquered land & goods / level." },
  armorer:     { k: "armorer",     per: 2, max: 28, axis: "prod",     txt: "+2% unit production / level." },
};
export const GEN_KEYS = Object.keys(GENERALS);
export const GEN_XP = [0, 5000, 10000, 20000, 50000, 100000, 200000, 400000];   // level thresholds (lvl = index)
export const genLevel = (xp) => { let l = 0; for (let i = 0; i < GEN_XP.length; i++) if (xp >= GEN_XP[i]) l = i; return l; };

// ---- missiles (4 types; exact research-point cost + effects; ½ effect outside war) --------------------
export const MISSILES = {
  conv:  { k: "conv",  cost: 100, txt: "Conventional — 15% of enemy bases, cascading readiness hit." },
  nuke:  { k: "nuke",  cost: 500, txt: "Nuclear — 10% land, 5% people, 3% units, −10% satisfaction." },
  bio:   { k: "bio",   cost: 250, txt: "Biocidal — 20% people, 5% soldiers & agents, −20% satisfaction." },
  emp:   { k: "emp",   cost: 300, txt: "EMP — 15% power plants, 15% energy, 10% mechs, 10% tech." },
};
export const MKEYS = Object.keys(MISSILES);

// ---- espionage operations (spy strength + ~20 ops; exact danger + effect) -----------------------------
export const ESPIONAGE = {
  infra_gov:    { k: "infra_gov",    cat: "infil", danger: 1, txt: "Infiltrate government — see buildings, tech, units." },
  infra_staff:  { k: "infra_staff",  cat: "infil", danger: 2, txt: "Infiltrate staff — army, alliances, rockets, spy strength." },
  infra_intel:  { k: "infra_intel",  cat: "infil", danger: 3, txt: "Infiltrate intelligence — exact agent count + their reports." },
  infra_sci:    { k: "infra_sci",    cat: "infil", danger: 2, txt: "Infiltrate research — tech-progress data." },
  sab_epidemic: { k: "sab_epidemic", cat: "sabo",  danger: 2, kill: 0.05, joy: 5, txt: "Spread epidemic — 5% people die, satisfaction falls." },
  sab_airfield: { k: "sab_airfield", cat: "sabo",  danger: 2, dmg: ["fighter", 0.04, 2], txt: "Sabotage airfield — destroy 4% fighters (≤2× agents)." },
  sab_parasite: { k: "sab_parasite", cat: "sabo",  danger: 3, dmg: ["farm", 0.03, 999], txt: "Deploy parasite — destroy 3% farms." },
  sab_virus:    { k: "sab_virus",    cat: "sabo",  danger: 3, techdmg: [0.04, 3], txt: "Computer virus — destroy 4% of all tech (≤3× agents)." },
  sab_mech:     { k: "sab_mech",     cat: "sabo",  danger: 3, dmg: ["mech", 0.04, 3], txt: "Sabotage mech controls — destroy 4% mechs (≤3× agents)." },
  sab_rockets:  { k: "sab_rockets",  cat: "sabo",  danger: 4, rockets: 1, txt: "Destroy missiles — a salvo per success." },
  sab_demoral:  { k: "sab_demoral",  cat: "sabo",  danger: 1, joy: 4, txt: "Demoralize — satisfaction falls (2× commune vs democ)." },
  sab_army:     { k: "sab_army",     cat: "sabo",  danger: 3, ready: 11, txt: "Sabotage army — cascade −11% readiness." },
  sab_agents:   { k: "sab_agents",   cat: "sabo",  danger: 1, agents: [0.05, 0.10], txt: "Murder agents — enemy agent casualties." },
  sab_hq:       { k: "sab_hq",       cat: "sabo",  danger: 4, agents: [0.15, 0.20], txt: "Attack HQ — enemy loses 15–20% of agents." },
  sab_amd:      { k: "sab_amd",      cat: "sabo",  danger: 3, techdmg: [0.15, 999], txt: "Damage air defense — ~15% of anti-missile tech." },
  theft_bank:   { k: "theft_bank",   cat: "theft", danger: 2, steal: "money",  unc: 0.25, cov: 0.01, capax: "prestige", txt: "Rob central bank — 25% liquid + 1% covered money." },
  theft_tech:   { k: "theft_tech",   cat: "theft", danger: 3, steal: "techPts", unc: 0.05, cov: 0.002, txt: "Steal technology — 5% of research." },
  theft_food:   { k: "theft_food",   cat: "theft", danger: 2, steal: "food",   unc: 0.25, cov: 0.01, capax: "prestige5", txt: "Plunder warehouses — 25% liquid + 1% covered food." },
  theft_energy: { k: "theft_energy", cat: "theft", danger: 2, steal: "energy", unc: 0.25, cov: 0.01, capax: "prestige5", txt: "Tap pipeline — 25% liquid + 1% covered energy." },
  theft_drugs:  { k: "theft_drugs",  cat: "theft", danger: 2, drugs: 1, gov: ["zealot", "dictator"], txt: "Sell drugs — money in, enemy satisfaction out (Zealotry/Dictatorship)." },
};
export const ESP_KEYS = Object.keys(ESPIONAGE);

// ---- domestic market base prices ($ per unit/ton/MWh) -------------------------------------------------
export const MARKET = { food: 25, energy: 25, soldier: 115, tank: 670, bunker: 500, fighter: 470, mech: 350, agent: 5000 };
// world-market trade tax: 6% on units, 10% on food/energy/tech
export const WM_TAX = { unit: 0.06, bulk: 0.10 };

// ---- advances (Pokroky): 5 types, difficulty-scaled cost ---------------------------------------------
// difficulty = 2 + advances/5 + land/10000 + prestige/1e6; final cost = base × difficulty (in tech points)
export const ADV_KINDS = { S: "social", K: "construction", T: "technological", A: "alliance", M: "alien" };
export const ADVANCES = {
  genome:      { k: "genome",      type: "S", base: 3000,  joy: 10,  txt: "Human Genome — +10% satisfaction." },
  fusion:      { k: "fusion",      type: "K", base: 4000,  noNukeCat: 1, txt: "Fusion Reactors — no nuclear catastrophe risk." },
  gmcrops:     { k: "gmcrops",     type: "K", base: 3500,  food: 0.15, genCat: 1, txt: "GM Crops — +15% food, but genetic-catastrophe risk." },
  intlcoop:    { k: "intlcoop",    type: "S", base: 4000,  embargoVote: 1, txt: "International Cooperation — an embargo vote." },
  censura:     { k: "censura",     type: "S", base: 3000,  censura: 1, txt: "Censorship — hides your ranking cards." },
  mafia:       { k: "mafia",       type: "T", base: 5000,  espOps: 5, wmRaze: 0.20, txt: "Mafia — +5 spy ops, +raze-on-market." },
  supercomp:   { k: "supercomp",   type: "M", base: 0,     econMax: 0.15, techProd: 0.15, txt: "Alien Supercomputer — +15% economic-tech max & tech output." },
  cyborg:      { k: "cyborg",      type: "M", base: 0,     cyborg: 1, txt: "Cyborg Foundry — turns 500 soldiers + 500 energy into 500 mechs / turn." },
  plasma:      { k: "plasma",      type: "M", base: 0,     plasma: 1, txt: "Plasma Weapons — weapon max 155%, +37.5% base effect." },
  smartmines:  { k: "smartmines",  type: "M", base: 0,     mineDef: 0.25, txt: "Smart Mines — +25% enemy losses on defense." },
  lunarbase:   { k: "lunarbase",   type: "K", base: 6000,  ufo: 1, txt: "Lunar Base — greatly boosts UFO odds." },
};
export const ADV_KEYS = Object.keys(ADVANCES);

// ---- alliance per-government bonus (× floor(members/2)) -----------------------------------------------
export const ALLY_BONUS = {
  anarchy: { build: 2 }, feudal: { prod: 0.01 }, democ: { econTech: 0.01 }, republic: { tax: 0.01 },
  technoc: { food: 0.01, energy: 0.01, tech: 0.01 }, commune: { spy: 0.03 }, zealot: { wage: -0.03 },
  dictator: { atk: 0.01 }, utopia: { joy: 0.01 }, robocr: { milTech: 0.01 },
};

// ---- random events (15; scope scales with the nation) ------------------------------------------------
export const EVENTS = [
  { k: "baby",     tone: "good", res: "people", pct: [0.01, 0.04], txt: "A baby boom swells the population." },
  { k: "harvest",  tone: "good", res: "food",   pct: [0.03, 0.10], txt: "A bumper harvest fills the granaries." },
  { k: "windfall", tone: "good", res: "money",  pct: [0.02, 0.08], txt: "A trade windfall floods the treasury." },
  { k: "surge",    tone: "good", res: "energy", pct: [0.03, 0.10], txt: "Grid efficiency spikes — energy surplus." },
  { k: "eureka",   tone: "good", res: "techPts",pct: [0.05, 0.20], txt: "A research breakthrough." },
  { k: "recruits", tone: "good", res: "soldier",pct: [0.02, 0.06], txt: "Patriots flock to the barracks." },
  { k: "festival", tone: "good", res: "joy",    flat: [2, 6],      txt: "A national festival lifts spirits." },
  { k: "calm",     tone: "neutral", txt: "A quiet turn — nothing of note." },
  { k: "drought",  tone: "bad",  res: "food",   pct: [-0.10, -0.03], txt: "Drought withers the fields." },
  { k: "recession",tone: "bad",  res: "money",  pct: [-0.08, -0.02], txt: "A downturn drains the treasury." },
  { k: "blackout", tone: "bad",  res: "energy", pct: [-0.10, -0.03], txt: "A blackout wastes stored energy." },
  { k: "plague",   tone: "bad",  res: "people", pct: [-0.05, -0.01], txt: "A plague takes lives." },
  { k: "strike",   tone: "bad",  res: "joy",    flat: [-6, -2],    txt: "Strikes sour the public mood." },
  { k: "desertion",tone: "bad",  res: "soldier",pct: [-0.06, -0.01], txt: "Desertions thin the ranks." },
  { k: "sabotage", tone: "bad",  res: "techPts",pct: [-0.10, -0.02], txt: "Industrial sabotage sets research back." },
];

// ---- deterministic hashing (shared with the contract's beacon rolls) ----------------------------------
import { blake2bHash } from "./nadotx.js?v=6d199166";
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
  const rockets = {}; for (const k of MKEYS) rockets[k] = 0;
  return {
    owner, day, land: START_LAND, bld, units, tech,
    people: 8000, money: 5000, food: 2000, energy: 1000,
    techPts: 0, comps: 0, gov: "feudal", joy: 60,            // joy = satisfaction %
    ready: 100, morale: 50, exp: 0, prestige: 0, ally: 0,
    rockets, rocketPts: 0,                                    // missile stock + research points (from bases)
    generals: [], advances: {},                              // [{type, xp}] · {advKey: 1}
    ufoExplore: 0, warTurns: 0, lastEvent: null,             // UFO progress · turns at war · last event log
    tick: 0,                                                  // turns elapsed at last settle (the lazy clock)
    bt: 0, btTick: 0,                                         // builds spent THIS turn + the turn they count for
    over: false,
  };
}
// ---- derived: veteran + general + advance modifier bundle used across production & war -----------------
export function generalBonus(n, axis) {              // multiplicative product of all generals on this axis
  let m = 1;
  for (const gen of n.generals || []) { const G = GENERALS[gen.type]; if (!G || G.axis !== axis) continue;
    const lv = genLevel(gen.xp); m *= 1 + Math.max(-0.7, Math.min(G.max / 100, G.per / 100 * lv)); }
  return m;
}
export const hasAdv = (n, k) => !!(n.advances && n.advances[k]);

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
  const gov = g(n), joyM = joyMul(n, 0.75), robots = !!gov.robots, vet = veteran(n);
  // money: every person earns; markets triple their land's tax; trade tech, gov, satisfaction stack
  let money = n.people * 0.0125;
  for (const k of BKEYS) if (B[k].money) money += n.bld[k] * B[k].money;
  money *= (1 + (n.bld.market * 2) / Math.max(1, n.land)) * techMul(n, "money") * (gov.m || 1) * joyM * (1 + allyB(n, "tax"));
  // food (agronomy tech + gov + GM crops advance)
  let food = 0; for (const k of BKEYS) if (B[k].food) food += n.bld[k] * B[k].food;
  food *= techMul(n, "food") * (gov.food || 1) * (hasAdv(n, "gmcrops") ? 1.15 : 1) * (1 + allyB(n, "food"));
  const eatPeople = n.people / 1000 * 0.25;
  const nonMech = UKEYS.reduce((s, k) => k === "mech" ? s : s + n.units[k], 0);
  const eatUnits = (robots ? 0 : nonMech / 1000 * 5) * vet.upkeepFood;   // rank 10: −15% consumption
  food -= eatPeople + eatUnits;
  // energy
  let mwh = 0; for (const k of BKEYS) if (B[k].mwh) mwh += n.bld[k] * B[k].mwh;
  mwh *= techMul(n, "energy") * (gov.e || 1) * (1 + allyB(n, "energy"));
  for (const k of BKEYS) mwh -= n.bld[k] * (B[k].hi ? 0.2 : B[k].lo ? 0.1 : 0);
  const totTech = TKEYS.reduce((s, k) => s + n.tech[k], 0);
  mwh -= (totTech / 1000 * 5 + (robots ? n.units.mech / 1000 * 5 : 0)) * vet.upkeepFood;
  // tech points (labs; satisfaction, gov, supercomputer advance)
  let tech = 0; for (const k of BKEYS) if (B[k].tech) tech += n.bld[k] * B[k].tech;
  tech *= joyMul(n, 0.5) * (gov.t || 1) * (hasAdv(n, "supercomp") ? 1.15 : 1) * (1 + allyB(n, "tech") + allyB(n, "econTech"));
  // components + soldier training (armorer general + gov + armorer)
  const comps = n.bld.factory * B.factory.comp * (gov.fac || 1) * generalBonus(n, "prod");
  const troops = n.bld.barracks * B.barracks.troop * (gov.bar || 1) * generalBonus(n, "prod");
  // missile research points from military bases (rank 12/13 speed up rocket dev)
  const rocketPts = n.bld.base * 8 * vet.rocketDev * techMul(n, "atk");
  // people growth toward capacity, scaled by satisfaction
  const cap = capacity(n);
  const grow = Math.max(0, cap - n.people) * 0.02 * clamp(n.joy / 60, 0.2, 1.6) + vet.expPerTurn * 0;
  return { money, food, energy: mwh, tech, comps, troops, grow, cap, rocketPts };
}

// per-turn salary bill (money) — economist general + rank 11 wage cut apply to soldiers
export function upkeep(n) {
  const vet = veteran(n), econ = generalBonus(n, "wage");
  return UKEYS.reduce((s, k) => s + n.units[k] * U[k].pay * (k === "soldier" ? vet.soldierWage : 1), 0) * econ;
}

// ---- settle: advance a nation by `turns` whole turns (the lazy production clock) -----------------------
// Deterministic and idempotent given (nation, turns). Starvation/blackout bite when a stock hits zero.
export function settle(n, turns) {
  turns = Math.max(0, Math.floor(turns));
  turns = Math.min(turns, MAX_BANK);                  // the source's bank cap: at most 140 unplayed rounds
  if (!turns || n.over) { n.tick += turns; return n; }
  for (let t = 0; t < turns && !n.over; t++) {
    const p = production(n), pay = upkeep(n), vet = veteran(n);
    n.money = clamp(n.money + p.money - pay, 0, CAP);
    n.food = clamp(n.food + p.food, 0, CAP);
    n.energy = clamp(n.energy + p.energy, 0, CAP);
    n.techPts += p.tech;
    n.comps += p.comps;
    n.rocketPts += p.rocketPts;
    n.units.soldier += Math.floor(p.troops);          // barracks train passively (the genre's cadence)
    // Cyborg Foundry advance: convert 500 soldiers + 500 energy → 500 mechs / turn (stops when short)
    if (hasAdv(n, "cyborg") && n.units.soldier >= 5000 && n.energy >= 5000) {
      n.units.soldier -= 500; n.energy -= 500; n.units.mech += 500;
    }
    // population: grow toward capacity; STARVE if food ran dry
    if (n.food <= 0) n.people = Math.max(0, Math.floor(n.people * 0.97));
    else n.people = clamp(Math.floor(n.people + p.grow), 0, capacity(n));
    // satisfaction drifts toward a target from arenas + gov + genome advance, minus the size penalty
    const target = clamp(50 + n.bld.arena * 0.5 * (g(n).joy || 1) + (hasAdv(n, "genome") ? 10 : 0) - n.land / 2000 - n.warTurns * 0.02, 5, 100);
    n.joy = clamp(n.joy + (target - n.joy) * 0.25, 0, 100);
    n.ready = clamp(n.ready + 4, 0, 100);             // army readiness recovers
    n.exp += vet.expPerTurn;                          // rank 9+ passive experience
    const tk = n.tick + t;                             // per-turn index → deterministic + turn-additive
    if (rollEvent(n, tk)) applyEvent(n, tk);           // rare random event (≈8%/turn)
    maybeCatastrophe(n, tk);                            // GM-crops / nuclear-plant disasters
    maybeUFO(n, tk);                                    // alien contact (round 480+, every 96)
  }
  n.tick += turns;
  return n;
}

// deterministic per-nation randomness for events/catastrophes (a pure function of owner + tick)
const nrand = (n, tk, salt) => Number(H("ev:" + n.owner + ":" + tk + ":" + salt) % 1000000n) / 1000000;
function rollEvent(n, tk) { return nrand(n, tk, "e") < 0.08; }
function applyEvent(n, tk) {
  const goodBias = n.joy > 75 ? 0.62 : n.joy < 55 ? 0.38 : 0.5;   // content nations get luckier
  const pool = EVENTS.filter((e) => nrand(n, tk, "tone") < goodBias ? e.tone !== "bad" : e.tone !== "good");
  const ev = (pool.length ? pool : EVENTS)[Math.floor(nrand(n, tk, "pick") * (pool.length || EVENTS.length))];
  n.lastEvent = ev.k;
  if (!ev.res) return;
  const r = ev.pct ? (ev.pct[0] + (ev.pct[1] - ev.pct[0]) * nrand(n, tk, "mag")) : 0;
  if (ev.res === "joy") { n.joy = clamp(n.joy + ev.flat[0] + (ev.flat[1] - ev.flat[0]) * nrand(n, tk, "mag"), 0, 100); return; }
  if (ev.res === "soldier") { n.units.soldier = Math.max(0, Math.floor(n.units.soldier * (1 + r))); return; }
  const cur = n[ev.res] || 0; n[ev.res] = clamp(Math.floor(cur * (1 + r)), 0, CAP);
}
function maybeCatastrophe(n, tk) {
  if (hasAdv(n, "gmcrops") && !hasAdv(n, "fusion") && nrand(n, tk, "gcat") < 0.004 * (n.bld.farm / Math.max(1, n.land))) catastrophe(n, tk);
  if (n.tech.power >= 8 && !hasAdv(n, "fusion") && nrand(n, tk, "ncat") < 0.003 * (n.bld.plant / Math.max(1, n.land))) catastrophe(n, tk);
}
function catastrophe(n, tk) {
  const r = 0.02 + 0.04 * nrand(n, tk, "csev");
  n.land = Math.floor(n.land * (1 - r)); n.bld.unbuilt = Math.max(0, n.bld.unbuilt - Math.floor(n.bld.unbuilt * r));
  n.units.soldier = Math.floor(n.units.soldier * (1 - r)); n.people = Math.floor(n.people * (1 - r));
  n.joy = clamp(n.joy - 8, 0, 100); n.lastEvent = "catastrophe";
}

// ---- actions (pure transitions; return true on success, false on illegal — the contract mirrors these) -
export function buildsPerTurn(n) { return Math.floor(12 + n.bld.builder / 6); }
export function buildCost(n, count) {          // total money for `count` new buildings (rising unit cost)
  const start = totalBuilt(n); let c = 0;
  for (let i = 0; i < count; i++) c += 300 + (start + i) * 0.3;
  return Math.round(c);
}
const totalBuilt = (n) => BUILDABLE.reduce((s, k) => s + n.bld[k], 0) + n.bld.ruin;

// builds still allowed THIS turn — the per-turn cap (12 + builders/6) minus what's already been built this
// turn. Resets when the turn advances. This makes the cap a true PER-TURN total, not a per-click limit, so
// clicking Build repeatedly in one turn can't exceed it (the extra actions replay as no-ops for everyone).
export function buildsLeft(n) {
  const used = (n.btTick === n.tick) ? (n.bt || 0) : 0;
  return Math.max(0, buildsPerTurn(n) - used);
}
export function build(n, type, count) {
  if (!BUILDABLE.includes(type) || count <= 0) return false;
  if (n.btTick !== n.tick) { n.bt = 0; n.btTick = n.tick; }  // new turn → fresh build budget
  if (count > buildsLeft(n)) return false;                   // per-TURN cap across repeated actions
  if (n.bld.unbuilt < count) return false;                  // must have open land
  const cost = buildCost(n, count);
  if (n.money < cost) return false;
  n.money -= cost; n.bld.unbuilt -= count; n.bld[type] += count; n.bt = (n.bt || 0) + count;
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

// ---- missiles: build from military-base research points; launch applies the exact effect --------------
export function buildMissile(n, type, count) {
  const M = MISSILES[type]; if (!M || count <= 0) return false;
  if (n.gov === "democ" && type === "bio") return false;             // democracies can't make biocidal
  const cost = M.cost * count;
  if (n.rocketPts < cost) return false;
  n.rocketPts -= cost; n.rockets[type] += count; return true;
}
// ---- advances (Pokroky): tech-point cost scaled by difficulty ----------------------------------------
export function advCost(n, key) {
  const A = ADVANCES[key]; if (!A) return Infinity;
  const owned = Object.keys(n.advances || {}).length;
  const diff = 2 + owned / 5 + n.land / 10000 + prestige(n) / 1e6;
  return Math.round(A.base * diff);
}
export function buildAdvance(n, key) {
  const A = ADVANCES[key]; if (!A || hasAdv(n, key)) return false;
  if (A.type === "M") return false;                                  // alien advances come only from UFO
  if (n.gov === "technoc" && key === "vaccination") return false;
  const cost = advCost(n, key);
  if (n.techPts < cost) return false;
  n.techPts -= cost; n.advances[key] = 1; return true;
}
// ---- domestic market: unit price rises as your stock of it falls (100–81% cheapest, 0–20% dearest) ----
export function unitPrice(n, type) {
  let base = MARKET[type];
  if (n.gov === "zealot" && type === "soldier") base = 95;          // fundamentalism-style discount
  if (n.gov === "commune" && type === "agent") base = 3000;
  base *= techMul(n, "atk") > 1 && U[type] && U[type].src === "factory" ? (2 - techMul(n, "atk")) : 1;   // weapon tech cheapens machines
  const cap = 20000, have = (type === "food" || type === "energy") ? n[type] : n.units[type] || 0;
  const stockFrac = clamp(have / cap, 0, 1);                        // more in stock → cheaper
  return Math.round(base * (1.6 - 0.6 * stockFrac));
}
export function marketBuy(n, type, count) {
  if (count <= 0) return false;
  if (type === "food" || type === "energy") { const cost = unitPrice(n, type) * count;
    if (n.money < cost) return false; n.money -= cost; n[type] = clamp(n[type] + count, 0, CAP); return true; }
  const u = U[type]; if (!u) return false;
  const cost = unitPrice(n, type) * count;
  if (n.money < cost) return false;
  n.money -= cost; n.units[type] += count; return true;
}
export function marketSell(n, type, count) {                        // sell to Country #0 at ~60% of buy price
  if (count <= 0) return false;
  const price = Math.floor(unitPrice(n, type) * 0.6);
  if (type === "food" || type === "energy") { if (n[type] < count) return false; n[type] -= count; n.money = clamp(n.money + price * count, 0, CAP); return true; }
  if (!U[type] || n.units[type] < count) return false;
  n.units[type] -= count; n.money = clamp(n.money + price * count, 0, CAP); return true;
}
// ---- generals: awarded probabilistically on a combat win (more army XP → likelier); level on XP -------
export function maybeAwardGeneral(n, seed, i) {
  const max = veteran(n).extraGeneral ? 4 : 3;
  if ((n.generals || []).length >= max) return;
  const chance = clamp(0.05 + n.exp / 5e6, 0.05, 0.35);
  if (roll(seed, "gen" + i) < chance) {
    const type = GEN_KEYS[Math.floor(roll(seed, "gt" + i) * GEN_KEYS.length)];
    n.generals.push({ type, xp: 0 });
  }
}

// ---- army strength -----------------------------------------------------------------------------------
// side="atk"|"def"; comp = {unit: fraction 0..1} for a normal attack (defaults to whole army on defense).
export function power(n, side, comp) {
  const gov = g(n), plasma = hasAdv(n, "plasma");
  const wm = techMul(n, "atk") * (plasma ? 1.15 : 1);                          // weapon-strength tech (plasma raises the cap)
  const baseM = 1 + n.bld.base / Math.max(1, n.land) * 0.2 * (plasma ? 1.375 : 1);
  const joyM = joyMul(n, 0.5), readyM = 0.4 + 0.6 * (n.ready / 100), expM = 1 + clamp(n.exp / 1e6, -0.2, 0.45);
  const vet = veteran(n), genM = generalBonus(n, side === "atk" ? "atk" : "def");
  let s = 0;
  for (const k of FIGHT_UNITS) {
    const q = comp ? Math.floor(n.units[k] * (comp[k] || 0)) : n.units[k];
    s += q * (side === "atk" ? U[k].a : U[k].d);
  }
  if (side === "def" && n.gov === "anarchy") s += Math.floor(n.people / 100);   // anarchy: people defend
  return s * wm * baseM * joyM * readyM * expM * genM * vet.armyStr * (gov.atk || 1) * (1 + allyB(n, "atk"));
}
// spy strength — source formula: agents/(land+2000) × (intel-tech+base bonus ×1000 + 10)
export function spyPower(n) {
  const bonus = techMul(n, "atk") - 1 + n.bld.base / Math.max(1, n.land) * 0.2;  // intel proxy + bases
  return n.units.agent / (n.land + 2000) * (bonus * 1000 + 10) * generalBonus(n, "spy");
}

// ---- combat: pure resolution of one raid; mutates BOTH nations, returns a report -----------------------
// atk/def already settled to the same turn. kind in ATTACK_KINDS; comp = attacker composition fractions.
// seed = block-hash-derived roll source (the contract passes the same). Returns { win, log fields }.
// combat(atk, def, kind, comp, seed, opts): opts.war doubles/triples XP (declared/active war). Applies the
// exact source composition bonuses, the conqueror general + rank-12 loot multiplier, the liberator general
// vs. more-prestigious foes, smart-mines defense, general/army XP, and probabilistic general awards.
export function combat(atk, def, kind, comp, seed, opts) {
  const K = ATTACK_KINDS[kind]; if (!K) return { ok: false };
  comp = comp || {};
  // composition fractions of the committed army (source bands): soldiers 0–80%→+money/tech, tanks 0–40%→
  // +territory, fighters 0–40%→+enemy losses, mechs 0–80%→−own losses.
  const frac = (k, capf) => clamp(comp[k] || 0, 0, 1) / (capf === 0.8 ? 1 : 1);
  const bSoldier = clamp((comp.soldier || 0), 0, 0.8) / 0.8 * 0.15;   // +money/tech
  const bTank = clamp((comp.tank || 0), 0, 0.4) / 0.4 * 0.15;          // +territory
  const bFighter = clamp((comp.fighter || 0), 0, 0.4) / 0.4 * 0.15;    // +enemy losses
  const bMech = clamp((comp.mech || 0), 0, 0.8) / 0.8 * 0.15;          // −own losses
  let ap = power(atk, "atk", comp);
  if (prestige(def) > prestige(atk)) ap *= generalBonus(atk, "vsBig");  // liberator
  let dp = power(def, "def", null);
  if (hasAdv(def, "smartmines")) dp *= 1.10;
  const swing = 0.85 + 0.3 * roll(seed, 0);                 // ±15% luck
  const win = ap * swing > dp;
  const rep = { ok: true, kind, win, ap: Math.round(ap), dp: Math.round(dp), lootLand: 0, loot: {}, razed: 0, defLoss: {}, atkLoss: {} };
  // casualties: loser bleeds more; mechs lose 20% less; +fighter% to enemy losses, −mech% to own losses,
  // smart-mines +25% to attacker losses.
  const fierce = kind === "annihilate" ? 0.5 : kind === "conquest" ? 0.4 : 0.35;
  const bleed = (nn, base, extra) => { for (const k of FIGHT_UNITS) {
    let r = base * (0.6 + 0.8 * roll(seed, k.length + (nn === atk ? 1 : 2))) * extra;
    if (k === "mech") r *= 0.8;
    const lost = Math.floor(nn.units[k] * clamp(r, 0, 0.95)); nn.units[k] -= lost;
    (nn === atk ? rep.atkLoss : rep.defLoss)[k] = lost;
  } };
  bleed(atk, fierce * (win ? 0.6 : 1.0), (1 - bMech) * (hasAdv(def, "smartmines") ? 1.25 : 1));
  bleed(def, fierce * (win ? 1.0 : 0.5), (1 + bFighter));
  atk.ready = clamp(atk.ready - 30, 0, 100);
  if (win) {
    const lootMul = generalBonus(atk, "loot") * veteran(atk).lootMul;   // conqueror + rank 12
    const band = (b, i) => (b[0] + (b[1] - b[0]) * roll(seed, 100 + i)) / 100;
    if (K.land[1]) { const take = Math.floor(def.land * band(K.land, 1) * lootMul * (1 + bTank));
      rep.lootLand = take; def.land -= take; atk.land += take;
      const fromUnbuilt = Math.min(def.bld.unbuilt, take); def.bld.unbuilt -= fromUnbuilt; atk.bld.unbuilt += take; }
    if (K.raze) {
      const r = band(K.loot, 2);
      for (const k of BUILDABLE) { const d = Math.floor(def.bld[k] * r); def.bld[k] -= d; def.bld.ruin += d; rep.razed += d; }
      for (const res of ["money", "food", "energy"]) { const d = Math.floor(def[res] * r); def[res] -= d; rep.loot[res] = -d; }
    } else {
      const r = band(K.loot, 3) * lootMul;
      for (const res of ["money", "food", "energy"]) { const bonus = res === "money" ? bSoldier : 0;
        const d = Math.floor(def[res] * r * (1 + bonus)); def[res] -= d; atk[res] = clamp(atk[res] + d, 0, CAP); rep.loot[res] = d; }
      const tsteal = Math.floor(def.techPts * band(K.loot, 4) * (1 + bSoldier)); def.techPts -= tsteal; atk.techPts += tsteal; rep.loot.tech = tsteal;
    }
    def.joy = clamp(def.joy - (kind === "annihilate" ? 12 : 6), 0, 100);
    def.ready = clamp(def.ready - 15, 0, 100);
    const xp = Math.floor((1500 + roll(seed, "xp") * 2000) * (opts && opts.war ? opts.war : 1));
    atk.exp += xp; rep.xp = xp;
    for (const gen of atk.generals || []) gen.xp += Math.floor(xp / 3);
    maybeAwardGeneral(atk, seed, atk.exp);
    atk.morale = clamp(atk.morale + 3, 0, 100);
  } else {
    atk.morale = clamp(atk.morale - 5, 0, 100);
    def.morale = clamp(def.morale + 2, 0, 100); def.exp += 200; rep.xp = 0;
  }
  return rep;
}

// ---- tactical attack: a single unit type vs a specific defense; exact source effects ------------------
export function tactical(atk, def, type, seed, opts) {
  const Tc = TACTICAL[type]; if (!Tc) return { ok: false };
  const u = Tc.unit;
  let ap = atk.units[u] * (U[u].a || U[u].d || 1) * (techMul(atk, "atk")) * (0.4 + 0.6 * atk.ready / 100) * generalBonus(atk, "tacAtk");
  let dp = Tc.def.reduce((s, k) => s + def.units[k] * (U[k].d || U[k].a || 1), 0) * techMul(def, "atk") * generalBonus(def, "tacDef");
  if (type === "nightraid") dp *= veteran(def).nightDef;   // rank 5 veteran bonus
  const win = ap * (0.85 + 0.3 * roll(seed, 0)) > dp;
  const rep = { ok: true, type, win, hit: 0 };
  atk.ready = clamp(atk.ready - Tc.ready, 0, 100);
  // attacker's own committed unit takes some losses either way
  const selfLoss = Math.floor(atk.units[u] * (win ? 0.03 : 0.10) * (0.6 + 0.8 * roll(seed, 5)));
  atk.units[u] -= selfLoss; rep.selfLoss = selfLoss;
  if (!win) { def.morale = clamp(def.morale + 1, 0, 100); return rep; }
  const b = Tc.band ? (Tc.band[0] + (Tc.band[1] - Tc.band[0]) * roll(seed, 3)) / 100 : 0;
  const hit = (field, isBld) => { const cur = isBld ? def.bld[field] : (field === "energy" ? def.energy : def.units[field]);
    const d = Math.floor(cur * b); if (isBld) { def.bld[field] -= d; if (BUILDABLE.includes(field)) def.bld.ruin += d; }
    else if (field === "energy") def.energy -= d; else def.units[field] -= d; rep.hit += d; return d; };
  if (Tc.hit === "energy") hit("energy", false);
  else if (Tc.hit === "tank") hit("tank", false);
  else if (Tc.hit === "base") hit("base", true);
  else if (Tc.hit === "building") { for (const k of BUILDABLE) { const d = Math.floor(def.bld[k] * b); def.bld[k] -= d; def.bld.ruin += d; rep.hit += d; }
    if (Tc.pop) def.people = Math.floor(def.people * (1 - (Tc.pop[1] / 100))); }
  else if (Tc.hit === "bunker") { const sup = clamp(atk.units.soldier / Math.max(1, def.units.soldier + 1) - 1, 0, 1);
    const d = Math.floor(def.units.bunker * 0.5 * sup); def.units.bunker -= d; rep.hit = d; }
  else if (Tc.hit === "baseunit") { hit("base", true); for (const k of ["mech", "tank"]) { const d = Math.floor(def.units[k] * b); def.units[k] -= d; rep.hit += d; } }
  atk.exp += Math.floor((300 + roll(seed, "x") * 500) * (opts && opts.war ? opts.war : 1));
  for (const gen of atk.generals || []) gen.xp += 60;
  return rep;
}

// ---- launch missiles: apply the exact effect; ½ effect outside a declared war (bio/emp/nuke) ----------
export function launchMissiles(atk, def, type, count, atWar) {
  const M = MISSILES[type]; if (!M || (atk.rockets[type] || 0) < count || count <= 0) return { ok: false };
  atk.rockets[type] -= count;
  // anti-missile defense (source: intel/space tech proxy) intercepts a share
  const intercept = clamp((def.tech.power || 0) * 0.05, 0, 0.8);
  const land = Math.max(0, count - Math.floor(count * intercept));
  const half = (type !== "conv" && !atWar) ? 0.5 : 1;
  const rep = { ok: true, type, fired: count, landed: land, intercepted: count - land, dmg: {} };
  for (let i = 0; i < land; i++) {
    if (type === "conv") { const d = Math.floor(def.bld.base * 0.15); def.bld.base -= d; def.bld.ruin += d; rep.dmg.base = (rep.dmg.base || 0) + d; def.ready = clamp(def.ready - 12, 0, 100); }
    else if (type === "nuke") { const dl = Math.floor(def.land * 0.10 * half); def.land -= dl; def.bld.unbuilt = Math.max(0, def.bld.unbuilt - dl);
      def.people = Math.floor(def.people * (1 - 0.05 * half)); for (const k of FIGHT_UNITS) def.units[k] = Math.floor(def.units[k] * (1 - 0.03 * half));
      def.joy = clamp(def.joy - 10 * half, 0, 100); rep.dmg.land = (rep.dmg.land || 0) + dl; }
    else if (type === "bio") { def.people = Math.floor(def.people * (1 - 0.20 * half)); def.units.soldier = Math.floor(def.units.soldier * (1 - 0.05 * half));
      def.units.agent = Math.floor(def.units.agent * (1 - 0.05 * half)); def.joy = clamp(def.joy - 20 * half, 0, 100); rep.dmg.people = 1; }
    else if (type === "emp") { const dp = Math.floor(def.bld.plant * 0.15 * half); def.bld.plant -= dp; def.bld.ruin += dp;
      def.energy = Math.floor(def.energy * (1 - 0.15 * half)); def.units.mech = Math.floor(def.units.mech * (1 - 0.10 * half));
      for (const k of TKEYS) def.tech[k] = Math.max(0, def.tech[k] - Math.ceil(def.tech[k] * 0.10 * half)); rep.dmg.plant = (rep.dmg.plant || 0) + dp; }
  }
  return rep;
}

// ---- espionage: run one operation with `send` agents; exact effects + danger-scaled agent losses ------
export function spyOp(atk, def, opKey, send, seed) {
  const O = ESPIONAGE[opKey]; if (!O || send <= 0 || atk.units.agent < send) return { ok: false };
  if (O.gov && !O.gov.includes(atk.gov)) return { ok: false };
  const sp = spyPower(atk) * send / Math.max(1, atk.units.agent), dpw = spyPower(def) + 1;
  const chance = clamp(sp / (sp + dpw) * (1 - O.danger * 0.08), 0.03, 0.95);
  const win = roll(seed, "sp") < chance;
  const rep = { ok: true, op: opKey, win, danger: O.danger, got: {}, lost: 0 };
  // agent losses: infiltration 0/1%, sabotage 2/4%, theft 0/4% (× spy general −losses)
  const lossRate = win ? (O.cat === "sabo" ? 0.02 : 0) : (O.cat === "infil" ? 0.01 : 0.04);
  const spyGen = 2 - generalBonus(atk, "spy");             // spy general also cuts agent losses
  rep.lost = Math.floor(send * lossRate * clamp(spyGen, 0.3, 1)); atk.units.agent -= rep.lost;
  if (!win) return rep;
  if (O.cat === "infil") { rep.intel = true; return rep; } // infiltration surfaces info to the UI
  if (O.kill) { def.people = Math.floor(def.people * (1 - O.kill)); def.joy = clamp(def.joy - (O.joy || 0), 0, 100); rep.got.people = 1; }
  if (O.dmg) { const [field, pct, cap] = O.dmg; const lim = Math.floor(send * (cap || 999));
    if (BUILDABLE.includes(field)) { const d = Math.min(lim, Math.floor(def.bld[field] * pct)); def.bld[field] -= d; def.bld.ruin += d; rep.got[field] = d; }
    else { const d = Math.min(lim, Math.floor(def.units[field] * pct)); def.units[field] -= d; rep.got[field] = d; } }
  if (O.techdmg) { const [pct] = O.techdmg; for (const k of TKEYS) def.tech[k] = Math.max(0, def.tech[k] - Math.ceil(def.tech[k] * pct)); rep.got.tech = 1; }
  if (O.ready) { def.ready = clamp(def.ready - O.ready, 0, 100); rep.got.ready = O.ready; }
  if (O.agents) { const d = Math.floor(def.units.agent * (O.agents[0] + (O.agents[1] - O.agents[0]) * roll(seed, "a"))); def.units.agent -= d; rep.got.agents = d; }
  if (O.rockets) { for (const k of MKEYS) if (def.rockets[k] > 0) { def.rockets[k] -= 1; rep.got.rockets = k; break; } }
  if (O.joy && !O.kill) { def.joy = clamp(def.joy - O.joy * (atk.gov === "commune" && def.gov === "democ" ? 2 : 1), 0, 100); rep.got.joy = O.joy; }
  if (O.steal) { const capMax = O.capax === "prestige" ? prestige(atk) : O.capax === "prestige5" ? prestige(atk) / 5 : Infinity;
    const liquid = Math.floor(def[O.steal] * O.unc), covered = Math.floor(def[O.steal] * (O.cov || 0));
    const got = Math.min(capMax, liquid + covered); def[O.steal] = Math.max(0, def[O.steal] - got);
    if (O.steal !== "techPts") atk[O.steal] = clamp((atk[O.steal] || 0) + got, 0, CAP); else atk.techPts += got; rep.got[O.steal] = got; }
  if (O.drugs) { const gain = Math.floor(def.people * 0.5); atk.money = clamp(atk.money + gain, 0, CAP); def.joy = clamp(def.joy - 3, 0, 100); rep.got.money = gain; }
  return rep;
}

// ---- action encoding + world replay (the on-chain model) ----------------------------------------------
// The contract is a THIN global append-only ACTION LOG (the stormhold free-actor pattern, world-scale):
// every player's action is one entry {actor, cursor, enc, target}. Every client REPLAYS the whole log
// through this engine to derive the world — settling each nation lazily between the actions that touch it,
// and resolving raids against a block-hash roll pinned by the entry's cursor. enc packs op + three 12-bit
// params; ATTACK carries the target address in its own field.
export const TURN_BLOCKS = 150;                   // one round per 150 L1 blocks = 15 min at 6s (faithful to Webgame: "nové kolo každých 15 minut", 96/day)
export const MAX_BANK = 140;                      // max unplayed rounds banked (the source's 140 cap) — offline production beyond this is forfeit
export const OP = { found: 0, build: 1, demolish: 2, recruit: 3, research: 4, revolt: 5, colonize: 6, attack: 7,
  missile: 8, tactical: 9, launch: 10, spy: 11, market: 12, advance: 13, alliance: 14, warcry: 15 };
const P = 4096;
export const encAction = (op, a = 0, b = 0, c = 0) => op + 16 * (a + P * (b + P * c));
export const decAction = (enc) => { let v = Math.floor(enc / 16); const op = enc % 16;
  const a = v % P; v = Math.floor(v / P); const b = v % P; const c = Math.floor(v / P); return { op, a, b, c, big: b + P * c }; };
// encBig: an op with an index `a` + a LARGE count (up to ~16M) packed across b+c (for recruit/market/spy).
export const encBig = (op, a, count) => encAction(op, a, count % P, Math.floor(count / P) % P);
// attack composition ⇄ 6-bit-per-unit eighths packed across b (soldier/tank/fighter) and c (bunker/mech)
export const packComp = (comp) => {
  const e = (k) => clamp(Math.round((comp[k] || 0) * 8), 0, 8);
  return { b: e("soldier") + 16 * e("tank") + 256 * e("fighter"), c: e("bunker") + 16 * e("mech") };
};
const unpackComp = (b, c) => ({ soldier: (b % 16) / 8, tank: (Math.floor(b / 16) % 16) / 8, fighter: (Math.floor(b / 256) % 16) / 8,
  bunker: (c % 16) / 8, mech: (Math.floor(c / 16) % 16) / 8 });

const turnsBetween = (fromCur, toCur) => Math.max(0, Math.floor((toCur - fromCur) / TURN_BLOCKS));

// applyAction(world, entry, seedOf): mutate the world by one log entry. seedOf(cursor)->BigInt|null (the
// block-hash roll for a raid; null = the seed block isn't final yet → the caller pauses replay). Returns
// "ok" | "blocked" | "skip" (an illegal/degenerate action is skipped, never corrupts — the fee already
// charged the actor). PROTECT_TURNS shields a young nation from raids.
export const PROTECT_TURNS = 60;
export function applyAction(world, e, seedOf, feed) {
  const { op, a, b, c, big } = decAction(e.enc);
  const note = (rep) => { if (feed && rep) feed.push({ op, actor: e.actor, target: e.target, cursor: e.cursor, rep }); return rep; };
  let n = world[e.actor];
  if (op === OP.found) { if (!n) { const nn = newNation(e.actor, Math.floor(e.cursor / (TURN_BLOCKS * 720)));
    nn.lastCur = e.cursor; world[e.actor] = nn; } return "ok"; }   // stamp the clock so a later touch settles from HERE
  if (!n) return "skip";
  settle(n, turnsBetween(n.lastCur ?? e.cursor, e.cursor)); n.lastCur = e.cursor;
  switch (op) {
    case OP.build:    return build(n, BUILDABLE[a], b) ? "ok" : "skip";
    case OP.demolish: return demolish(n, BKEYS[a], b) ? "ok" : "skip";
    case OP.recruit:  return recruit(n, UKEYS[a], big) ? "ok" : "skip";
    case OP.research: return research(n, TKEYS[a]) ? "ok" : "skip";
    case OP.revolt:   return revolt(n, GKEYS[a]) ? "ok" : "skip";
    case OP.colonize: return colonize(n) ? "ok" : "skip";
    case OP.missile:  return buildMissile(n, MKEYS[a], b) ? "ok" : "skip";
    case OP.advance:  return buildAdvance(n, ADV_KEYS[a]) ? "ok" : "skip";
    case OP.alliance: { if (a === 1) { n.ally = 0; n.exp = Math.floor(n.exp * 2 / 3); return "ok"; }  // leave: −1/3 XP
      if (n.tick > 500 && !n.ally) return "skip";           // can't found/join an alliance after turn 500 allianceless
      n.ally = b || 0; return "ok"; }                        // join/create alliance id b
    case OP.warcry: { const d = world[e.target]; if (!d) return "skip";
      // declare war between the two nations' alliances: both sides' war clocks start (XP ×2 while at war)
      n.warTurns = Math.max(n.warTurns, 1); if (d.warTurns != null) d.warTurns = Math.max(d.warTurns, 1); return "ok"; }
    case OP.market: { const sub = Math.floor(a / 64), ti = a % 64, item = MARKET_ITEMS[ti];
      if (!item) return "skip";
      return (sub === 0 ? marketBuy(n, item, big) : marketSell(n, item, big)) ? "ok" : "skip"; }
    case OP.attack: case OP.tactical: case OP.launch: case OP.spy: {
      const d = world[e.target]; if (!d || e.target === e.actor) return "skip";
      settle(d, turnsBetween(d.lastCur ?? e.cursor, e.cursor)); d.lastCur = e.cursor;
      if (d.tick < PROTECT_TURNS && prestige(d) < 200) return "skip";   // newbie shield (age + weak)
      const seed = seedOf(e.rh ?? e.cursor); if (seed == null) return "blocked";   // roll from the FUTURE seed block
      const atWar = (n.warTurns || 0) > 0 || (d.warTurns || 0) > 0;
      if (op === OP.attack) { if (n.ready < 40) return "skip"; note(combat(n, d, Object.keys(ATTACK_KINDS)[a] || "plunder", unpackComp(b, c), seed, { war: atWar ? 2 : 1 })); return "ok"; }
      if (op === OP.tactical) { if (n.ready < 20) return "skip"; note(tactical(n, d, TKEYS_TAC[a] || "partisan", seed, { war: atWar ? 2 : 1 })); return "ok"; }
      if (op === OP.launch) { const r = launchMissiles(n, d, MKEYS[a], b, atWar); if (r.ok) note(r); return r.ok ? "ok" : "skip"; }
      if (op === OP.spy) { const r = spyOp(n, d, ESP_KEYS[a], big, seed); if (r.ok) note(r); return r.ok ? "ok" : "skip"; }
      return "skip";
    }
    default: return "skip";
  }
}
export const MARKET_ITEMS = ["food", "energy", "soldier", "tank", "fighter", "bunker", "mech", "agent"];

// replayWorld(entries, nowCur, seedOf): fold the whole log into { addr: nation }, then settle every nation
// forward to `nowCur` for display. blocked=true (+blockedAt) when a raid's seed block isn't final yet.
export function replayWorld(entries, nowCur, seedOf) {
  const feed = [], world = {}, res = { world, feed, blocked: false, blockedAt: -1 };
  for (let i = 0; i < entries.length; i++) {
    const r = applyAction(world, entries[i], seedOf, feed);
    if (r === "blocked") { res.blocked = true; res.blockedAt = i; break; }
  }
  computeAlliances(world);                             // roster + aggregated bonus onto each member (n._ally)
  for (const addr in world) { const n = world[addr];
    settle(n, turnsBetween(n.lastCur ?? nowCur, nowCur)); n.lastCur = nowCur; }
  return res;
}
// group nations by alliance id (≤10 members), aggregate each government's ALLY_BONUS × floor(members/2),
// and stash {id, members, bonus} on every member so production()/power() can read it.
export function computeAlliances(world) {
  const rosters = {};
  for (const addr in world) { const n = world[addr]; n._ally = null; if (n.ally) (rosters[n.ally] = rosters[n.ally] || []).push(n); }
  for (const id in rosters) {
    const members = rosters[id].slice(0, 10), mul = Math.floor(members.length / 2);
    const bonus = {};
    for (const m of members) { const ab = ALLY_BONUS[m.gov]; if (!ab) continue;
      for (const k in ab) bonus[k] = (bonus[k] || 0) + ab[k] * mul; }
    for (const m of members) m._ally = { id: +id, members: members.length, bonus };
  }
}
export const allyB = (n, k) => (n._ally && n._ally.bonus[k]) || 0;

// ---- UFO / alien contact (round 480+, a window every 96 turns; odds from bases + Lunar Base advance) --
// Refusing raises exploration +10% (implicit: a miss); accepting grants an alien advance and −30% explore.
function maybeUFO(n, tk) {
  if (tk < 480 || tk % 96 !== 0) return;
  const odds = clamp((n.bld.base / Math.max(1, n.land)) * 0.5 + (hasAdv(n, "lunarbase") ? 0.4 : 0) + n.ufoExplore / 100, 0, 0.95);
  if (nrand(n, tk, "ufo") < odds) {
    const aliens = ADV_KEYS.filter((k) => ADVANCES[k].type === "M" && !hasAdv(n, k));
    if (aliens.length && nrand(n, tk, "ufoacc") < 0.6) {       // accept a gift
      n.advances[aliens[Math.floor(nrand(n, tk, "ufopick") * aliens.length)]] = 1;
      n.ufoExplore = Math.max(0, n.ufoExplore - 30); n.lastEvent = "ufo";
    } else { n.ufoExplore += 10; }                             // refuse: exploration climbs
  } else { n.ufoExplore += 2; }
}

// ---- medals: threshold achievements (levels 1–3), a pure function for display ------------------------
export const MEDAL_TIERS = {
  prestige:  { get: (n) => prestige(n),           lv: [600000, 1200000, 3600000] },
  territory: { get: (n) => n.land,                lv: [5000, 10000, 20000] },
  people:    { get: (n) => n.people,              lv: [1000000, 5000000, 10000000] },
  soldiers:  { get: (n) => n.units.soldier,       lv: [300000, 1000000, 2000000] },
  tanks:     { get: (n) => n.units.tank,          lv: [15000, 75000, 200000] },
  agents:    { get: (n) => n.units.agent,         lv: [2000, 5000, 15000] },
  armyexp:   { get: (n) => n.exp,                 lv: [75000, 100000, 150000] },
  nukes:     { get: (n) => n.rockets ? n.rockets.nuke : 0, lv: [1, 3, 7] },
};
export function medals(n) {
  const out = {};
  for (const k in MEDAL_TIERS) { const M = MEDAL_TIERS[k], v = M.get(n); let lv = 0;
    for (let i = 0; i < M.lv.length; i++) if (v >= M.lv[i]) lv = i + 1; if (lv) out[k] = lv; }
  return out;
}

// ---- prestige (the world-ranking score) — EXACT source point values ----------------------------------
// soldier 1 · tank 5 · fighter 3.5 · bunker 3.5 · mech 2.7 · agent 15 · rocket 500 · 1 km² 15 ·
// building 5 · ruin 2 · technology 1 · 1000$ 2 · 100t food 2 · 100 MWh 2. (Advances/generals/experience/
// rank do NOT count toward prestige — source.)
export function prestige(n) {
  let s = n.land * 15;
  for (const k of BUILDABLE) s += n.bld[k] * 5;
  s += (n.bld.ruin || 0) * 2;
  for (const k of UKEYS) s += n.units[k] * U[k].pres;                 // pres = exact per-unit value
  s += rocketCount(n) * 500;
  for (const k of TKEYS) s += n.tech[k];                              // 1 per technology LEVEL... (see note)
  s += Math.floor(n.money / 1000) * 2 + Math.floor(n.food / 100) * 2 + Math.floor(n.energy / 100) * 2;
  return Math.floor(s);
}
export const rocketCount = (n) => MKEYS.reduce((t, k) => t + (n.rockets ? (n.rockets[k] || 0) : 0), 0);

// ---- ranks & veteran bonuses (14 ranks by army experience; bonuses stack) ----------------------------
export const RANKS = [
  { k: "farmer",   xp: 0 },        { k: "recruit",  xp: 10000 },   { k: "bunkercmd", xp: 20000 },
  { k: "scout",    xp: 40000 },    { k: "tankcmd",  xp: 80000 },   { k: "mechcmd",   xp: 150000 },
  { k: "airlt",    xp: 250000 },   { k: "guardcpt", xp: 400000 },  { k: "major",     xp: 600000 },
  { k: "colonel",  xp: 850000 },   { k: "general",  xp: 1150000 }, { k: "armygen",   xp: 1500000 },
  { k: "kapo",     xp: 1950000 },  { k: "peoplenemy", xp: 2450000 },
];
export function rankOf(n) { let r = 0; for (let i = 0; i < RANKS.length; i++) if (n.exp >= RANKS[i].xp) r = i; return r; }
// veteran bonuses unlocked by rank (index into RANKS): rank 5(mechcmd)=+10% night-raid def; rank 7(guard
// captain)= agent per 400 fallen soldiers; rank 8(major)=4th general; rank 9(colonel)=+100 exp/turn; rank
// 10(general)=-15% food/energy use; rank 11(armygen)=-25% soldier wages; rank 12(kapo)=+25% loot +50%
// rocket dev; rank 13(peoplenemy)=+10% army strength +100% rocket dev.
export function veteran(n) {
  const r = rankOf(n);
  return {
    nightDef: r >= 5 ? 1.10 : 1, extraGeneral: r >= 8, expPerTurn: r >= 9 ? 100 : 0,
    upkeepFood: r >= 10 ? 0.85 : 1, soldierWage: r >= 11 ? 0.75 : 1,
    lootMul: r >= 12 ? 1.25 : 1, rocketDev: r >= 13 ? 2 : (r >= 12 ? 1.5 : 1), armyStr: r >= 13 ? 1.10 : 1,
  };
}
