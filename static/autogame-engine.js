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
import * as R from "./autogame-rules.js";
export * from "./autogame-rules.js";

// ── integer helpers, matching the VM exactly ────────────────────────────────────────────────────
export const csub = (a, b) => (a > b ? a - b : 0);            // clamped: the field wraps, so this is law
const idiv = (a, b) => Math.floor(a / b);
const imod = (a, b) => a - b * Math.floor(a / b);

// ── item packing ────────────────────────────────────────────────────────────────────────────────
// A gear cell holds 1 + tier*64 + mat*8 + affix, so 0 unambiguously means "empty" — the VM deletes a slot
// written with zero, so 0 can never be a legal item.
export function unpackItem(v) {
  if (!v) return { tier: -1, mat: 0, affix: 0 };
  const body = v - 1;
  return { tier: idiv(body, 64), mat: imod(idiv(body, 8), 8), affix: imod(body, 8) };
}
export const packItem = (tier, mat, affix) => 1 + tier * 64 + mat * 8 + affix;
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
    alive: m("av"), done: m("dn"), retired: m("rt"),
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
export const weaponPts = (run) => idiv(weaponPower(run) * run.focus, 100);
export const armorPts = (run) => idiv(armorPower(run) * (100 - run.focus), 100);

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

/** Tile class as a count of thresholds passed — literally what the contract computes. */
export function tileOf(a, depth) {
  if (depth > 0 && imod(depth, R.BOSS_EVERY) === 0) return R.BOSS;
  let k = 0;
  for (const cut of R.TILE_CUTS) if (a >= cut) k++;
  return k;
}
export function monsterLevel(tile, depth) {
  let ml = 1 + tierOf(depth);
  if (tile === R.ELITE) ml += 2;
  else if (tile === R.BOSS) ml += 4;
  if (isNight(depth)) ml += 1;
  return ml;
}

export function rollItem(c, z, depth, bonus) {
  let tier = Math.min(7, tierOf(depth) + imod(c, 3) + bonus);
  if (imod(c, R.JACKPOT_EVERY) === 0) tier = 7;      // the jackpot ignores depth entirely
  const mat = imod(idiv(c, 8), 8);
  const affix = imod(z, 4) === 0 ? 1 + imod(idiv(z, 4), 7) : 0;
  return packItem(tier, mat, affix);
}

function takeItemAt(run, slot, item) {
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

function tryCraft(run) {
  const [s, h, e] = run.mats;
  const wantW = run.wlevel < R.LEVEL_CAP && s >= R.SHARPEN_COST[0] && e >= R.SHARPEN_COST[2];
  const wantA = run.alevel < R.LEVEL_CAP && s >= R.REINFORCE_COST[0] && h >= R.REINFORCE_COST[1];
  if (wantW && (run.focus >= 50 || !wantA)) {
    run.mats[0] -= R.SHARPEN_COST[0]; run.mats[2] -= R.SHARPEN_COST[2]; run.wlevel += 1; return 1;
  }
  if (wantA) {
    run.mats[0] -= R.REINFORCE_COST[0]; run.mats[1] -= R.REINFORCE_COST[1]; run.alevel += 1; return 2;
  }
  return 0;
}

// ── the engagement — MAMEC's formula ────────────────────────────────────────────────────────────
function fight(run, tile, b, x, y, z, agg, act, ev) {
  const depth = run.depth;
  const ml = monsterLevel(tile, depth);
  const fam = imod(b, 3);
  const bv = idiv(b, 3);
  const foes = tile === R.BOSS ? 1 : agg;             // a boss is one big thing, not a crowd
  const [dmgNum, expNum, streakGain, streakCap] = R.STANCES[run.stance];

  let atkEach = R.FAM_ATK[fam][0] + R.FAM_ATK[fam][1] * ml + imod(bv, 4);
  let xpEach = R.FAM_XP[fam][0] + R.FAM_XP[fam][1] * ml;
  if (tile === R.BOSS) { atkEach *= 4; xpEach *= 12; }

  // damage in: stance, reaction, ±10% variance, then PER-ENGAGEMENT absorption
  atkEach = idiv(atkEach * dmgNum, 4);
  if (act === R.A_STRIKE) atkEach = idiv(atkEach * 5, 4);
  else if (act === R.A_GUARD) atkEach = idiv(atkEach * 2, 4);
  atkEach = idiv(atkEach * (100 + imod(x, 21) - 10), 100);
  const absorb = armorPts(run) * (hasAffix(run, R.AF_HEAVY) ? foes : 1);
  let dmg = csub(foes * atkEach, absorb);
  if (dmg < foes) dmg = foes;                         // a horde always draws blood

  // renown out — bloodlust reads the hp you went IN with
  const hpBefore = run.hp;
  const wp = weaponPts(run);
  let base = idiv(foes * xpEach * (R.HORDE_DIV + foes), R.HORDE_DIV);
  base = idiv(base * (8 + wp), 8);
  base += idiv(wp * run.kills, 64);
  base = idiv(base * expNum, 4);
  if (act === R.A_STRIKE) base = idiv(base * 5, 4);
  const bl = run.maxhp + 4 * csub(run.maxhp, hpBefore);
  let gain = idiv(base * bl, run.maxhp);

  const streak = Math.min(streakCap + R.KEEN_BONUS * hasAffix(run, R.AF_KEEN), run.streak);
  gain = idiv(gain * (R.STREAK_DIV + streak), R.STREAK_DIV);
  run.streak += streakGain;
  if (act === R.A_POTION) gain = 0;                   // drinking forfeits your offence

  run.kills += foes;
  run.xp += gain;
  Object.assign(ev, { ml, fam, foes, dmg, gain, streak: run.streak });

  const drops = idiv(foes * 4 + imod(z, 5), 5);
  if (drops) { run.mats[fam] += drops; ev.drops = drops; ev.mat = fam; }

  // hp: regen + lifesteal - damage, then the easy-win clamp
  const regen = Math.min(idiv(run.maxhp, R.REGEN_CAP_DIV), idiv(run.xp, R.REGEN_DIV));
  const drain = idiv(wp, R.LIFESTEAL_DIV) * (1 + hasAffix(run, R.AF_VAMP));
  let hp = csub(hpBefore + regen + drain, dmg);
  hp = csub(hp, imod(y, 2));
  if (hp >= hpBefore) { hp = csub(hpBefore, imod(y, 2)); ev.easy = 1; }   // "easy win! no healing."
  run.hp = Math.min(run.maxhp, hp);
  ev.drain = drain;

  if (tile === R.BOSS || tile === R.ELITE || imod(z, 4) === 0 || hasAffix(run, R.AF_BLAZE)) {
    const bonus = tile === R.BOSS ? 2 : tile === R.ELITE ? 1 : 0;
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
export function step(run, tw, rw, act, agg) {
  if (!run.alive || run.done || run.retired) return { tile: R.ROAD, skip: true };

  const depth = run.depth;
  const { a, b, c, scen } = sliceTile(tw);
  const { x, y, z } = sliceRoll(rw);
  let tile = tileOf(a, depth);
  const tier = tierOf(depth);

  // a fork is a CHOICE: the right lane re-rolls as an elite, the left as a monster
  if (tile === R.FORK) { tile = act === R.A_RIGHT ? R.ELITE : R.MONSTER; act = R.A_DEFAULT; }

  run.stam = Math.min(R.STAM_MAX, run.stam + 1 + R.SWIFT_BONUS * hasAffix(run, R.AF_SWIFT));
  if (R.COST[act] > run.stam) act = R.A_DEFAULT;      // unaffordable reactions degrade, never revert
  run.stam -= R.COST[act];
  agg = Math.max(1, Math.min(R.AGG_MAX, agg));

  const ev = { tile, act, agg, scen, depth, dmg: 0, gain: 0, item: 0, slot: -1 };
  const combat = tile === R.MONSTER || tile === R.ELITE || tile === R.BOSS;
  const skip = act === R.A_SPRINT || act === R.A_DODGE;

  // the reaction and the tile resolve INDEPENDENTLY; `act` holds one value so only one of these fires
  if (act === R.A_RALLY) {                            // the only heal that keeps the streak
    run.hp = Math.min(run.maxhp, run.hp + R.RALLY_BASE + tier);
    run.stam = Math.min(R.STAM_MAX, run.stam + 2);
    ev.rally = 1;
  }
  if (act === R.A_REST) {                             // MAMEC's rest: buy hp with score
    const heal = 8 + idiv(run.xp, 32);
    run.hp = Math.min(run.maxhp, run.hp + heal);
    run.xp = csub(run.xp, 4 + idiv(run.xp, 20));
    run.banked = Math.min(run.banked, run.xp);
    run.streak = 0;
    ev.rest = heal;
  }
  if (act === R.A_POTION) ev.drank = drink(run) ? 1 : 0;

  if (!skip) {
    if (combat) {
      fight(run, tile, b, x, y, z, agg, act, ev);
    } else if (tile === R.HAZARD) {
      let took = 2 + 2 * tier + imod(y, 6);
      if (run.stance === R.ST_EVASIVE) took = idiv(took, 2);
      took = csub(took, idiv(armorPts(run), 8));
      if (hasAffix(run, R.AF_WARD)) took = 0;         // warding: hazards do nothing
      run.hp = csub(run.hp, took);
      ev.dmg = took;
    } else if (tile === R.CACHE || tile === R.RELIC) {
      const item = rollItem(c, z, depth, tile === R.RELIC ? 3 : 0);
      const slot = imod(z, R.NSLOT);
      takeItemAt(run, slot, item);
      ev.item = item; ev.slot = slot;
    } else if (tile === R.SHRINE) {
      run.hp = Math.min(run.maxhp, run.hp + R.SHRINE_BASE + 4 * tier);
      run.potions = Math.min(R.POTION_CAP, run.potions + (imod(z, 4) === 0 ? 1 : 0));
      run.streak = 0;                                 // a shrine is a heal like any other
      ev.heal = 1;
    } else if (tile === R.FORGE) {
      ev.craft = tryCraft(run);
      if (run.mats[0] >= R.POTION_PRICE && run.potions < R.POTION_CAP) {
        run.mats[0] -= R.POTION_PRICE; run.potions += 1; ev.bought = 1;
      }
    }
  } else {
    ev[act === R.A_SPRINT ? "sprint" : "dodge"] = 1;
  }

  // the standing order — what keeps an absent player alive, and under bloodlust the sharpest dial there is
  if (run.hp > 0 && run.potions > 0 && run.hp * 100 < run.maxhp * run.healpct) {
    if (drink(run)) ev.auto = 1;
  }

  run.depth = depth + 1;
  if (run.hp === 0) { run.alive = 0; ev.died = 1; }
  else if (run.depth >= R.CHAPTER) { run.done = 1; ev.chapter = 1; }
  return ev;
}

// ── driving a leg ───────────────────────────────────────────────────────────────────────────────
/** Unpack a packed plan word into its 16 three-bit reactions. */
export function unpackPlan(word) {
  const acts = [];
  let w = BigInt(word || 0);
  for (let i = 0; i < R.LEG; i++) { acts.push(Number(w & 7n)); w >>= 3n; }
  return acts;
}
export function packPlan(acts) {
  let w = 0n;
  for (let i = 0; i < Math.min(acts.length, R.LEG); i++) w |= BigInt(acts[i] & 7) << BigInt(3 * i);
  return w.toString();
}

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
export function playLeg(algHashn, run, runId, tileHash, rollHash, planWord, agg) {
  const acts = unpackPlan(planWord);
  const evs = [];
  for (let i = 0; i < R.LEG; i++) {
    if (!run.alive || run.done || run.retired) break;
    const tw = words(algHashn, tileHash, runId, i);
    const rw = words(algHashn, rollHash, runId, i);
    evs.push(step(run, tw, rw, acts[i], agg));
  }
  return evs;
}

/**
 * The ROAD AHEAD: what the next LEG tiles are, derived from a hash that already exists. This is the whole
 * reason the game has skill in it — you can see the terrain before you commit reactions to it, while the
 * dice that resolve them come from a height that does not exist yet.
 */
export function peekLeg(algHashn, run, runId, tileHash) {
  const out = [];
  for (let i = 0; i < R.LEG; i++) {
    const tw = words(algHashn, tileHash, runId, i);
    const { a, b, c, scen } = sliceTile(tw);
    const depth = run.depth + i;
    let tile = tileOf(a, depth);
    const fam = imod(b, 3);
    out.push({
      i, depth, tile, scen, fam,
      ml: tile === R.MONSTER || tile === R.ELITE || tile === R.BOSS || tile === R.FORK
        ? monsterLevel(tile === R.FORK ? R.MONSTER : tile, depth) : 0,
      // the heaviest single swing waiting here — the number your aggression has to be priced against
      swing: (() => {
        const t = tile === R.FORK ? R.ELITE : tile;
        if (t !== R.MONSTER && t !== R.ELITE && t !== R.BOSS) return 0;
        const ml = monsterLevel(t, depth);
        return R.FAM_ATK[fam][0] + R.FAM_ATK[fam][1] * ml + imod(idiv(b, 3), 4);
      })(),
    });
  }
  return out;
}
