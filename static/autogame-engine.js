// autogame-engine.js — the deterministic march engine, in the browser.
//
// This is the THIRD implementation of the same program. `execnode/games/autogame.py` (zkasm) is
// authoritative and decides what actually happened on chain; `tests/autogame_model.py` is the readable
// Python reference; this is what the client runs to animate a leg, to preview a plan before you commit it,
// and to let anyone verify a run without trusting a node. All three must agree step for step — a
// divergence is a bug in the other two until proven otherwise (doc/autogame.md).
//
// Every constant comes from ./autogame-rules.js, which is GENERATED from the contract. Nothing here
// restates a number, because the one way three implementations silently drift apart is by each keeping its
// own copy of the tuning table.
//
// INTEGER DISCIPLINE. The VM is integer-only over a prime field, so every division here is a floor
// division on a non-negative value (`(a / b) | 0` is only safe below 2^31, so `Math.floor` is used) and
// every subtraction goes through `csub`, which clamps at zero. A bare `a - b` that can go negative is the
// bug that makes a browser preview disagree with the chain.
import * as R from "./autogame-rules.js?v=e7abffe6";
export * from "./autogame-rules.js?v=e7abffe6";

// ── integer helpers, matching the VM exactly ────────────────────────────────────────────────────
export const csub = (a, b) => (a > b ? a - b : 0);            // clamped: the field wraps, so this is law
const idiv = (a, b) => Math.floor(a / b);
const imod = (a, b) => a - b * Math.floor(a / b);

// ── item packing ────────────────────────────────────────────────────────────────────────────────
// A gear cell packs 1 + kind*512 + tier*64 + mat*8 + affix — `kind` is the WEAPON CLASS (0..3), meaningful
// only in the weapon slot; every other slot rolls kind 0. 0 still means "empty" (the VM deletes a zero
// slot). tier now reads through a %8 window because `kind` sits directly above it.
export function unpackItem(v) {
  if (!v) return { kind: 0, tier: -1, mat: 0, affix: 0 };
  const body = v - 1;
  return { kind: imod(idiv(body, 512), 4), tier: imod(idiv(body, 64), 8), mat: imod(idiv(body, 8), 8), affix: imod(body, 8) };
}
export const packItem = (tier, mat, affix, kind = 0) => 1 + kind * 512 + tier * 64 + mat * 8 + affix;
// The class of the currently EQUIPPED weapon (W_SWORD for a bare-handed run — a neutral baseline).
export const weaponKind = (run) => unpackItem(run.gear[R.G_WEAPON]).kind;
export function power(v) {
  if (!v) return 0;
  const it = unpackItem(v);
  return it.tier * 4 + it.mat;
}
export const hasAffix = (run, a) => (run.gear.some((g) => g && unpackItem(g).affix === a) ? 1 : 0);

// ── the run record — field names match the contract's storage map 1:1 ───────────────────────────
export function newRun(opts = {}) {
  return {
    hp: R.HP0, maxhp: R.HP0, stam: R.STAM_MAX, potions: R.POTIONS0,
    xp: 0, banked: 0, streak: 0, depth: 0, kills: 0,
    stance: opts.stance ?? R.ST_BALANCED,
    healpct: opts.healpct ?? 35,
    focus: opts.focus ?? 50,
    wlevel: 1, alevel: 1,
    mats: [0, 0, 0],
    gear: new Array(R.NSLOT).fill(0),
    agg: 1,          // the aggression dial — the one standing order besides stance/focus/healpct
    gale: 0,         // storm steps left: renown out and damage in both x5/4
    pyre: 0,         // lit-beacon steps left: renown out x5/4, no damage rider
    alive: 1, done: 0, retired: 0,
  };
}

/** Read a run straight out of the contract's storage view, so the animator and the chain start level. */
export function runFromStorage(sto, id) {
  const m = (name) => Number((sto[name] || {})[id] || 0);
  return {
    hp: m("hp"), maxhp: m("mx"), stam: m("st"), potions: m("po"), xp: m("xp"), banked: m("bk"),
    streak: m("sk"), depth: m("dp"), kills: m("ki"), stance: m("sn"), healpct: m("hl"), focus: m("fo"),
    wlevel: m("wl"), alevel: m("al"), mats: [m("m0"), m("m1"), m("m2")],
    gear: [m("g0"), m("g1"), m("g2"), m("g3"), m("g4"), m("g5")],
    alive: m("lv"), done: m("dn"), retired: m("rt"), gale: m("gl"), pyre: m("py"),
    agg: Math.max(1, m("pa")), polh: m("ph"),
    prevAgg: Math.max(1, m("qa")), polph: m("qh"),
    prevStance: m("qs"), prevFocus: m("qf"), prevHealpct: m("ql"),
    lh: m("lh"), nh: m("nh"), leg: m("lg"), owner: (sto.ra || {})[id],
  };
}

// ── derived stats ───────────────────────────────────────────────────────────────────────────────
export const weaponPower = (run) => 2 * run.wlevel + power(run.gear[R.G_WEAPON]);
export function armorPower(run) {
  let d = 4 + 3 * run.alevel;
  for (let s = 1; s < R.NSLOT; s++) d += idiv(power(run.gear[s]), R.DEF_DIV[s]);
  return d;
}
// `focus` is the GOVERNING generation's, which is not necessarily the one currently stored on the run
export const weaponPts = (run, focus) => idiv(weaponPower(run) * (focus == null ? run.focus : focus), 100);
export const armorPts = (run, focus) => idiv(armorPower(run) * (100 - (focus == null ? run.focus : focus)), 100);

/** What the board shows. Banked + what you carry out, and the road bonus only if you are standing. */
export function score(run) {
  const risk = csub(run.xp, run.banked);
  const standing = run.alive || run.done || run.retired;
  const total = run.banked + (standing ? risk : idiv(risk * R.DEATH_KEEP, 100));
  if (run.done) return total + R.COMPLETE_BONUS;
  if (run.retired) return total + idiv(R.COMPLETE_BONUS * run.depth, R.CHAPTER);
  return total;
}
export function rankOf(xp) {
  for (const [t, n] of R.RANKS) if (xp < t) return n;
  return "creator";
}

// ── world derivation ────────────────────────────────────────────────────────────────────────────
/** Slice the tile word exactly as the contract does — same order, same divisors. */
export function sliceTile(tw) {
  return {
    a: imod(tw, 100),
    b: imod(idiv(tw, 100), 64),
    c: imod(idiv(tw, 6400), 64),
    // scenery detail is renderer-only: the contract deliberately never derives it (its divisor exceeds
    // DIVMOD's window, and consensus pays for nothing it does not decide)
    scen: imod(idiv(tw, 409600), 8192),
  };
}
export function sliceRoll(rw) {
  return { x: imod(rw, 100), y: imod(idiv(rw, 100), 64), z: imod(idiv(rw, 6400), 64) };
}

export const tierOf = (depth) => idiv(depth, R.TIER_EVERY);
export const isNight = (depth) => imod(idiv(depth, R.NIGHT_EVERY), 2) === 1;

// ── biomes ──────────────────────────────────────────────────────────────────────────────────────
// THE CHAIN ROLLS THE REALM. Each leg's biome comes from the same terrain hash its tiles do — visible
// the moment the leg's terrain is, unknowable before it — drifting one realm either side of the depth
// stage, so a march wanders Greenwood → Fen → Crags → Ashway → Nether as the chapter deepens but never
// on a fixed schedule. Consensus never pays for it: like scenery, the biome decides which CREATURES and
// backdrops the renderer shows, never a stat — the contract deliberately does not derive it (the same
// precedent as the tile word's 4th field).
export const BIOMES = 5;
export const BIOME_NAMES = ["greenwood", "fen", "crags", "ashway", "nether"];
// 4096 as the index tag: playLeg/peekLeg address steps by their in-leg index (< LEG) and the Daily
// Gauntlet by absolute step (< 128), so 4096+legIndex can never collide with a step's word.
export function biomeFor(algHashn, tileHash, runId, depth) {
  const stage = Math.min(BIOMES - 1, idiv(depth * BIOMES, R.CHAPTER));
  const w = Number(algHashn([tileHash, runId, 4096 + idiv(depth, R.LEG)]) & 0xFFFFFFFFn);
  const b = stage + imod(w, 3) - 1;
  return Math.max(0, Math.min(BIOMES - 1, b));
}

/** Tile class as a count of thresholds passed — literally what the contract computes. */
export function tileOf(a, depth) {
  if (depth > 0 && imod(depth, R.BOSS_EVERY) === 0) return R.BOSS;
  let k = 0;
  for (const cut of R.TILE_CUTS) if (a >= cut) k++;
  return k;
}
export function monsterLevel(tile, depth) {
  let ml = 1 + tierOf(depth);
  if (tile === R.ELITE || tile === R.MIMIC) ml += 2;  // a mimic fights at elite level
  else if (tile === R.BOSS) ml += 4;
  if (isNight(depth)) ml += 1;
  if (tile === R.HORDE) ml = Math.max(1, ml - 2);     // many and weak: two levels down, floored
  return ml;
}

export function rollItem(c, z, depth, bonus) {
  let tier = Math.min(7, tierOf(depth) + imod(c, 3) + bonus);
  if (imod(c, R.JACKPOT_EVERY) === 0) tier = 7;      // the jackpot ignores depth entirely
  const mat = imod(idiv(c, 8), 8);
  const affix = imod(z, 4) === 0 ? 1 + imod(idiv(z, 4), 7) : 0;
  const kind = imod(c + z, 4);                        // WEAPON CLASS — matters only if this lands in slot 0
  return packItem(tier, mat, affix, kind);
}

function takeItemAt(run, slot, item) {
  // Auto-equip if strictly better, else melt for scrap. The player ADAPTS TO THE GEAR THE ROAD GIVES:
  // no inventory, no take-backs.
  const nw = power(item), old = power(run.gear[slot]);
  if (nw > old) {
    run.gear[slot] = item;
    run.mats[0] += 1 + idiv(old, 8);
    return true;
  }
  run.mats[0] += 1 + idiv(nw, 8);
  return false;
}

function drink(run) {
  if (run.potions <= 0) return false;
  run.potions -= 1;
  run.hp = Math.min(run.maxhp, run.hp + R.HEAL_BASE + 4 * tierOf(run.depth));
  if (!hasAffix(run, R.AF_HALLOW)) run.streak = 0;   // hallowed: the heal keeps the streak
  return true;
}

function tryCraft(run, focus) {
  if (focus == null) focus = run.focus;
  const [s, h, e] = run.mats;
  const wantW = run.wlevel < R.LEVEL_CAP && s >= R.SHARPEN_COST[0] && e >= R.SHARPEN_COST[2];
  const wantA = run.alevel < R.LEVEL_CAP && s >= R.REINFORCE_COST[0] && h >= R.REINFORCE_COST[1];
  if (wantW && (focus >= 50 || !wantA)) {
    run.mats[0] -= R.SHARPEN_COST[0]; run.mats[2] -= R.SHARPEN_COST[2]; run.wlevel += 1; return 1;
  }
  if (wantA) {
    run.mats[0] -= R.REINFORCE_COST[0]; run.mats[1] -= R.REINFORCE_COST[1]; run.alevel += 1; return 2;
  }
  return 0;
}

// ── the engagement — MAMEC's formula ────────────────────────────────────────────────────────────
function fight(run, tile, b, x, y, z, agg, act, ev, stance, focus) {
  if (stance == null) stance = run.stance;
  if (focus == null) focus = run.focus;
  const depth = run.depth;
  const ml = monsterLevel(tile, depth);
  const fam = imod(b, 3);
  const bv = idiv(b, 3);
  // a boss is one big thing; a HORDE is twice the bodies (capped at the dial's max), and Dodge cannot
  // slip a horde — it only halves the pull back to the plain number (Sprint is the clean escape)
  const foes = (tile === R.BOSS || tile === R.MIMIC) ? 1   // a mimic does not come in packs
    : tile === R.HORDE ? (act === R.A_DODGE ? agg : Math.min(R.AGG_MAX, agg * 2))
    : agg;
  const [dmgNum, expNum, streakGain, streakCap] = R.STANCES[stance];

  let atkEach = R.FAM_ATK[fam][0] + R.FAM_ATK[fam][1] * ml + imod(bv, 4);
  let xpEach = R.FAM_XP[fam][0] + R.FAM_XP[fam][1] * ml;
  if (tile === R.BOSS) { atkEach *= 4; xpEach *= 12; }
  else if (tile === R.MIMIC) { atkEach *= 2; xpEach *= 4; }  // bites double, pays 4x

  // damage in: stance, reaction, ±10% variance, then PER-ENGAGEMENT absorption
  atkEach = idiv(atkEach * dmgNum, 4);
  if (act === R.A_STRIKE) atkEach = idiv(atkEach * 5, 4);
  atkEach = idiv(atkEach * (100 + imod(x, 21) - 10), 100);
  const absorb = armorPts(run, focus) * (hasAffix(run, R.AF_HEAVY) ? foes : 1);
  // guard coverage: the shield takes HALF of up to TWO foes' swings; the rest of the pull hits full
  let total = foes * atkEach;
  if (act === R.A_GUARD) total = csub(total, Math.min(foes, 2) * idiv(atkEach, 2));
  let dmg = csub(total, absorb);
  if (dmg < foes) dmg = foes;                         // a horde always draws blood

  // renown out — bloodlust reads the hp you went IN with
  const hpBefore = run.hp;
  const wp = weaponPts(run, focus);
  let base = idiv(foes * xpEach * (R.HORDE_DIV + foes), R.HORDE_DIV);
  base = idiv(base * (8 + wp), 8);
  base += idiv(wp * run.kills, 64);
  base = idiv(base * expNum, 4);
  if (act === R.A_STRIKE) base = idiv(base * 5, 4);
  const bl = run.maxhp + 4 * csub(run.maxhp, hpBefore);
  let gain = idiv(base * bl, run.maxhp);
  // AMBUSH danger pay (+25% renown) and the GALE amplifier (+25% renown out AND damage in), in the
  // contract's exact spot: after bloodlust, before the streak
  if (tile === R.AMBUSH) gain = idiv(gain * 5, 4);
  if (run.gale > 0) { gain = idiv(gain * 5, 4); dmg = idiv(dmg * 5, 4); }
  if (run.pyre > 0) gain = idiv(gain * 5, 4);   // the lit beacon: +25% renown, no damage rider

  // WEAPON CLASS — the equipped weapon rewrites the engagement against a different axis of the road. Applied
  // here, after every environmental rider and before the streak, so it stacks the same way they do. Kept to
  // the game's ×5/4 / ×3/2 / ×3/4 quantum so it tunes rather than upends the balance the sim already set.
  const wk = weaponKind(run);
  if (wk === R.W_AXE) { gain = idiv(gain * 5, 4); dmg = idiv(dmg * 5, 4); }        // aggressor
  else if (wk === R.W_MAUL) {                                                       // crusher
    if (tile === R.BOSS || tile === R.ELITE || tile === R.MIMIC) gain = idiv(gain * 3, 2);
    else if (foes > 1) gain = idiv(gain * 3, 4);
  } else if (wk === R.W_SPEAR) {                                                    // skirmisher
    if (foes > 1) dmg = idiv(dmg * 3, 4);
    else gain = idiv(gain * 3, 4);
  }

  const streak = Math.min(streakCap + R.KEEN_BONUS * hasAffix(run, R.AF_KEEN), run.streak);
  gain = idiv(gain * (R.STREAK_DIV + streak), R.STREAK_DIV);
  if (act !== R.A_GUARD) run.streak += streakGain;   // no momentum behind a shield: guarded fights pause the streak
  if (act === R.A_POTION) gain = 0;                   // drinking forfeits your offence

  run.kills += foes;
  run.xp += gain;
  Object.assign(ev, { ml, fam, foes, dmg, gain, streak: run.streak });

  const drops = idiv(foes * 4 + imod(z, 5), 5);
  if (drops) { run.mats[fam] += drops; ev.drops = drops; ev.mat = fam; }

  // hp: regen + lifesteal - damage, then the easy-win clamp
  const regen = Math.min(idiv(run.maxhp, R.REGEN_CAP_DIV), idiv(run.xp, R.REGEN_DIV));
  const drain = idiv(wp * foes, R.LIFESTEAL_DIV) * (1 + hasAffix(run, R.AF_VAMP));   // per BODY
  let hp = csub(hpBefore + regen + drain, dmg);
  hp = csub(hp, imod(y, 2));
  if (hp >= hpBefore) { hp = csub(hpBefore, imod(y, 2)); ev.easy = 1; }   // "easy win! no healing."
  run.hp = Math.min(run.maxhp, hp);
  ev.drain = drain;

  if (tile === R.BOSS || tile === R.ELITE || tile === R.MIMIC || imod(z, 4) === 0 || hasAffix(run, R.AF_BLAZE)) {
    const bonus = (tile === R.BOSS || tile === R.MIMIC) ? 2 : tile === R.ELITE ? 1 : 0;  // a mimic IS treasure
    const item = rollItem(imod(b + z, 64), z, depth, bonus);
    const slot = imod(z, R.NSLOT);
    takeItemAt(run, slot, item);
    ev.item = item; ev.slot = slot;
  }
  if (tile === R.BOSS) {                              // the CHECKPOINT
    run.banked = run.xp;
    run.maxhp += 10;
    run.potions = Math.min(R.POTION_CAP, run.potions + 1);
    ev.banked = run.banked;
  }
}

// ── the step ────────────────────────────────────────────────────────────────────────────────────
/**
 * Advance one tile. `tw`/`rw` are the two 32-bit hash windows, `act` this tile's queued reaction, `agg`
 * the leg's aggression dial. Mutates `run` and returns an event describing what to animate.
 */
export function step(run, tw, rw, agg, stance, focus, healpct, action) {
  if (!run.alive || run.done || run.retired) return { tile: R.ROAD, skip: true };
  // the GOVERNING generation of DIALS — passing them explicitly is how a caller models a leg fenced to an
  // older generation (the contract's POLH rule); the ACTION needs no such care, it was committed before
  // the leg's dice were scheduled by construction
  if (agg == null) agg = run.agg;
  if (stance == null) stance = run.stance;
  if (focus == null) focus = run.focus;
  if (healpct == null) healpct = run.healpct;

  const depth = run.depth;
  const { a, b, c, scen } = sliceTile(tw);
  const { x, y, z } = sliceRoll(rw);
  let tile = tileOf(a, depth);
  const tier = tierOf(depth);

  // YOUR ANSWER to this exact tile — the only action channel there is (manual-only). 0 IS an action:
  // A_DEFAULT, walk in and fight plainly.
  let act = (action || 0) & 7;

  // a fork is a CHOICE: the right lane re-rolls as an elite, the left as a monster
  if (tile === R.FORK) { tile = act === R.A_RIGHT ? R.ELITE : R.MONSTER; act = R.A_DEFAULT; }
  // TOLLGATE robbery is the same shape: Strike cracks the reeve's strongbox and the STRONGBOX BITES —
  // a MIMIC fight (one body, elite level, double teeth, 4x renown, always drops). The Strike stays.
  if (tile === R.TOLLGATE && act === R.A_STRIKE) tile = R.MIMIC;

  run.stam = Math.min(R.STAM_MAX, run.stam + 1 + R.SWIFT_BONUS * hasAffix(run, R.AF_SWIFT));
  let cost = R.COST[act];
  if (stance === R.ST_EVASIVE && (act === R.A_DODGE || act === R.A_SPRINT)) cost -= 1;   // evasive footwork
  if (cost > run.stam) act = R.A_DEFAULT;             // unaffordable reactions degrade, never revert
  else run.stam -= cost;
  agg = Math.max(1, Math.min(R.AGG_MAX, agg));

  const ev = { tile, act, agg, scen, depth, dmg: 0, gain: 0, item: 0, slot: -1 };
  const combat = tile === R.MONSTER || tile === R.HORDE || tile === R.ELITE
    || tile === R.AMBUSH || tile === R.MIMIC || tile === R.BOSS;
  // Sprint always slips; Dodge slips everything EXCEPT a horde (too many bodies — fight() halves the
  // pull instead). That asymmetry is Sprint's reason to exist.
  const skip = act === R.A_SPRINT || (act === R.A_DODGE && tile !== R.HORDE);

  // the reaction and the tile resolve INDEPENDENTLY; `act` holds one value so only one of these fires
  if (act === R.A_RALLY) {                            // the only heal that keeps the streak — and it
    run.hp = Math.min(run.maxhp, run.hp + R.RALLY_BASE + tier);  // pays its FULL 3 stamina (no refund:
    ev.rally = 1;                                                // all-rally must starve, not sustain)
  }
  if (act === R.A_REST) {                             // MAMEC's rest: buy hp with score. At a CAMP the
    const camp = tile === R.CAMP;                     // fire is laid: heal DOUBLES, the renown price waived
    const heal = (8 + idiv(run.xp, 32)) * (camp ? 2 : 1);
    run.hp = Math.min(run.maxhp, run.hp + heal);
    if (!camp) run.xp = csub(run.xp, 4 + idiv(run.xp, 20));
    run.banked = Math.min(run.banked, run.xp);
    run.streak = 0;
    ev.rest = heal;
    if (camp) ev.camp = 1;
  }
  // at an idol the flask is an OFFERING, at a well it is BOTTLED — neither is a drink
  if (act === R.A_POTION && tile !== R.IDOL && tile !== R.WELL) ev.drank = drink(run) ? 1 : 0;

  // AMBUSH strikes first: an armour-free sting of 2 per level unless the answer was Guard or Dodge.
  // It lands even on a Sprint-past.
  if (tile === R.AMBUSH && act !== R.A_GUARD && act !== R.A_DODGE) {
    const sting = 2 * monsterLevel(tile, depth);
    run.hp = csub(run.hp, sting);
    ev.sting = sting;
  }
  // the TOLLGATE'S LASH: dashing past the chain (Dodge/Sprint) skips the toll but not the whip
  if (tile === R.TOLLGATE && (act === R.A_DODGE || act === R.A_SPRINT)) {
    const lash = 2 + 2 * tier;
    run.hp = csub(run.hp, lash);
    ev.lash = lash;
  }
  // GALE arms the storm for the next three steps (the end-of-step decay eats one on this tile, hence 4)
  // — unless you answered Dodge and sheltered.
  if (tile === R.GALE && act !== R.A_DODGE) { run.gale = 4; ev.gale = 1; }

  if (!skip) {
    if (combat) {
      fight(run, tile, b, x, y, z, agg, act, ev, stance, focus);
    } else if (tile === R.HAZARD) {
      let took = 2 + 2 * tier + imod(y, 6);
      if (stance === R.ST_EVASIVE) took = idiv(took, 2);
      took = csub(took, idiv(armorPts(run, focus), 8));
      if (hasAffix(run, R.AF_WARD)) took = 0;         // warding: hazards do nothing
      run.hp = csub(run.hp, took);
      ev.dmg = took;
    } else if (tile === R.CACHE || tile === R.RELIC || tile === R.BARROW || tile === R.ARMORY) {
      // one merged loot family: relic +3, barrow +1, armory FORCED to the weapon rack
      const item = rollItem(c, z, depth, tile === R.RELIC ? 3 : tile === R.BARROW ? 1 : 0);
      const slot = tile === R.ARMORY ? R.G_WEAPON : imod(z, R.NSLOT);
      takeItemAt(run, slot, item);
      ev.item = item; ev.slot = slot;
      if (tile === R.BARROW) {                    // the grave-curse: armour-free; Guard halves, ward voids
        let curse = 2 + 2 * tier;
        if (act === R.A_GUARD) curse = idiv(curse, 2);
        if (hasAffix(run, R.AF_WARD)) curse = 0;
        run.hp = csub(run.hp, curse);
        ev.curse = curse;
      }
    } else if (tile === R.SNARE) {
      if (act === R.A_GUARD) { run.mats[0] += 2; ev.sprung = 1; }   // sprung on the shield: +2 scrap
      else { run.stam = csub(run.stam, 3); ev.snare = 1; }
    } else if (tile === R.QUAG) {
      let took = 1 + tier;                        // armour is useless in a bog; Evasive wades it halved
      if (stance === R.ST_EVASIVE) took = idiv(took, 2);
      run.hp = csub(run.hp, took);
      run.stam = csub(run.stam, 2);
      ev.quag = took;
    } else if (tile === R.TOLLGATE) {             // walked through: the reeve takes ~3% of the whole pile
      const toll = 4 + idiv(run.xp, 32);
      run.xp = csub(run.xp, toll);
      run.banked = Math.min(run.banked, run.xp);
      ev.toll = toll;
    } else if (tile === R.VEIN) {
      if (act === R.A_STRIKE) { const mined = 4 + 2 * tier + imod(z, 3); run.mats[0] += mined; ev.mined = mined; }
    } else if (tile === R.GROVE) {
      if (act === R.A_RALLY) {                    // commune: essence + the spirits keep your momentum
        const ess = 2 + idiv(tier, 2) + imod(z, 2);
        run.mats[2] += ess; run.streak += 1; ev.commune = ess;
      }
    } else if (tile === R.WELL) {
      if (act === R.A_REST) {                     // drink deep: stamina to FULL plus a small heal
        run.stam = R.STAM_MAX;
        run.hp = Math.min(run.maxhp, run.hp + idiv(R.SHRINE_BASE, 2) + 2 * tier);
        ev.well = 1;
      } else if (act === R.A_POTION) {            // bottle the spring: +1 flask, streak kept
        run.potions = Math.min(R.POTION_CAP, run.potions + 1);
        ev.bottled = 1;
      }
    } else if (tile === R.PYRE) {
      if (act === R.A_STRIKE) { run.pyre = 4; ev.pyre = 1; }   // light the beacon
    } else if (tile === R.IDOL) {
      const base2 = idiv((20 + 20 * tier) * (run.maxhp + 4 * csub(run.maxhp, run.hp)), run.maxhp);
      if (act === R.A_STRIKE) { run.xp += base2; ev.gain = base2; }
      else if (act === R.A_POTION && run.potions > 0) {
        run.xp += base2 * 3; run.potions -= 1; ev.gain = base2 * 3; ev.offered = 1;
      }
    } else if (tile === R.SHRINE) {
      run.hp = Math.min(run.maxhp, run.hp + R.SHRINE_BASE + 4 * tier);
      run.potions = Math.min(R.POTION_CAP, run.potions + (imod(z, 4) === 0 ? 1 : 0));
      run.streak = 0;                                 // a shrine is a heal like any other
      ev.heal = 1;
    } else if (tile === R.FORGE) {
      ev.craft = tryCraft(run, focus);
      if (run.mats[0] >= R.POTION_PRICE && run.potions < R.POTION_CAP) {
        run.mats[0] -= R.POTION_PRICE; run.potions += 1; ev.bought = 1;
      }
    }
  } else {
    ev[act === R.A_SPRINT ? "sprint" : "dodge"] = 1;
  }

  run.gale = csub(run.gale, 1);                       // the storm blows itself out one step at a time
  run.pyre = csub(run.pyre, 1);                       // …and the beacon burns down the same way

  // the standing order — what keeps an absent player alive, and under bloodlust the sharpest dial there is
  if (run.hp > 0 && run.potions > 0 && run.hp * 100 < run.maxhp * healpct) {
    if (drink(run)) ev.auto = 1;
  }

  run.depth = depth + 1;
  if (run.hp === 0) { run.alive = 0; ev.died = 1; }
  else if (run.depth >= R.CHAPTER) { run.done = 1; ev.chapter = 1; }
  // Presentation snapshot: the run AS OF THIS STEP, so the HUD can tick along with the animation
  // instead of jumping straight to the leg's end state. Consensus never reads these — events are
  // neither hashed nor cross-checked field-by-field (the differential tests compare RUN fields).
  ev.hp = run.hp; ev.maxhp = run.maxhp; ev.stam = run.stam; ev.pots = run.potions;
  ev.xp2 = run.xp; ev.bank2 = run.banked; ev.strk = run.streak; ev.gale2 = run.gale;
  ev.dp2 = run.depth;
  return ev;
}

// ── driving a leg ───────────────────────────────────────────────────────────────────────────────
/**
 * The two 32-bit windows for step `i`, given an L1 block hash already reduced into the field.
 * `algHashn` is injected rather than imported so this module stays dependency-free and can be run by a
 * headless verifier: pass the browser's alghash port (nadodapp exports it).
 */
export function words(algHashn, blockHashField, runId, i) {
  return Number(algHashn([blockHashField, runId, i]) & 0xFFFFFFFFn);
}

/**
 * Replay one leg: `tileHash`/`rollHash` are BHASH(lh) and BHASH(nh) reduced into the field. Returns the
 * per-step events so the renderer can animate what already happened on chain.
 */
export function playLeg(algHashn, run, runId, tileHash, rollHash, dials, answerWord) {
  const o = dials || {};
  const acts = unpackLeg(answerWord);
  const evs = [];
  for (let i = 0; i < R.LEG; i++) {
    if (!run.alive || run.done || run.retired) break;
    const tw = words(algHashn, tileHash, runId, i);
    const rw = words(algHashn, rollHash, runId, i);
    // the biome rides on the EVENT, not in step(): it is presentation derived from the same hash, and
    // the consensus step function must never grow a field the contract does not compute
    const biome = biomeFor(algHashn, tileHash, runId, run.depth);
    evs.push(Object.assign(step(run, tw, rw, o.agg, o.stance, o.focus, o.healpct, acts[i]), { biome }));
  }
  return evs;
}

/** A leg's answer word <-> 16 three-bit actions, step 0 in the low bits. 0 = A_DEFAULT. */
export function unpackLeg(word) {
  const out = [];
  let w = BigInt(word || 0);
  for (let i = 0; i < R.LEG; i++) { out.push(Number(w & 7n)); w >>= 3n; }
  return out;
}
export function packLeg(acts) {
  let w = 0n;
  for (let i = 0; i < Math.min(acts.length, R.LEG); i++) w |= BigInt(acts[i] & 7) << BigInt(3 * i);
  // A NUMBER, never a string. The exec layer digests EVERY string argument as an address
  // (runtimes.zkvm_statement) — even "12345" — so a stringified word arrives as a ~2^64 digest, fails the
  // contract's `word < 2^48` require, and every commit from the browser reverts with no feedback at all.
  // That was live: "I click commit these sixteen and nothing happens." 16 x 3 bits = 48 bits, exact in a
  // double, so Number is lossless here.
  return Number(w);
}

/**
 * Which generation of DIALS governs a leg with rolling height `nh`: the newest one that PREDATES it.
 * Mirrors the contract's POLH fence exactly — current if old enough, else the superseded generation,
 * else neutral defaults (a leg older than any orders you ever gave).
 */
export function dialsFor(run, nh) {
  if ((run.polh || 0) < nh) {
    return { agg: run.agg, stance: run.stance, focus: run.focus, healpct: run.healpct };
  }
  if ((run.polph || 0) < nh) {
    return { agg: run.prevAgg, stance: run.prevStance, focus: run.prevFocus, healpct: run.prevHealpct };
  }
  return { agg: 1, stance: R.ST_BALANCED, focus: 50, healpct: 35 };
}



/**
 * The ROAD AHEAD: what the next LEG tiles are, derived from a hash that already exists. This is the whole
 * reason the game has skill in it — you can see the terrain before you commit reactions to it, while the
 * dice that resolve them come from a height that does not exist yet.
 * `from`/`n` exist for the Daily Gauntlet, which walks one continuous road of 124 steps instead of legs of
 * 16: it peeks at absolute step indices. Defaulting them to (0, LEG) leaves the chain-paced caller exactly
 * as it was, and means the Gauntlet's road strip is built by this function rather than a second copy of it.
 */
export function peekLeg(algHashn, run, runId, tileHash, from = 0, n = R.LEG) {
  const out = [];
  for (let i = from; i < from + n; i++) {
    const tw = words(algHashn, tileHash, runId, i);
    const { a, b, c, scen } = sliceTile(tw);
    const depth = run.depth + (i - from);
    let tile = tileOf(a, depth);
    const fam = imod(b, 3);
    out.push({
      i, depth, tile, scen, fam,
      biome: biomeFor(algHashn, tileHash, runId, depth),
      ml: [R.MONSTER, R.HORDE, R.ELITE, R.AMBUSH, R.MIMIC, R.BOSS, R.FORK, R.TOLLGATE].includes(tile)
        ? monsterLevel(tile === R.FORK || tile === R.TOLLGATE ? R.MONSTER : tile, depth) : 0,
      // the heaviest single swing waiting here — the number your aggression has to be priced against.
      // A fork's right lane resolves as an ELITE; a robbed tollgate as the strongbox MIMIC.
      swing: (() => {
        const t = tile === R.FORK ? R.ELITE : tile === R.TOLLGATE ? R.MIMIC : tile;
        if (![R.MONSTER, R.HORDE, R.ELITE, R.AMBUSH, R.MIMIC, R.BOSS].includes(t)) return 0;
        const ml = monsterLevel(t, depth);
        const mult = t === R.MIMIC ? 2 : 1;
        return (R.FAM_ATK[fam][0] + R.FAM_ATK[fam][1] * ml + imod(idiv(b, 3), 4)) * mult;
      })(),
    });
  }
  return out;
}
