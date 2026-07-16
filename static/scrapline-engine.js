// scrapline-engine.js — the full rules engine for NADO Scrapline, an ORIGINAL cooldown auto-battler with
// inventory management (a genre homage — inspired by "From Rust To Ash" by LokiStriker, which is
// all-rights-reserved: nothing here is ported; every item, name, number and line of code is original;
// game mechanics are not copyrightable). Deterministic and headless-testable (browser + node).
//
// Shape: a 2-player staked duel on the stormhold/chess contract (escrow + free-actor move log + agree
// settle). DRAFT: 9 rounds each, CONCURRENT — every player draws their own offer stream. The offer a
// player sees for round r derives from the seed height pinned by their PREVIOUS move (the join-time kh
// for round 1): HASH(bh(rh)+bh(rh+1)+salt+i) — unpredictable when the pick before it was signed, and
// replayable by any browser. Six gear slots; picking a duplicate (same item, same rank) MERGES into a
// higher rank; replacing scraps the old item for max-HP; skipping the whole offer scraps it for max-HP.
// COMBAT: once both players have drafted, the fight resolves as a PURE deterministic simulation of the
// two builds (deciseconds, cooldown fires, shields, burn, tag synergies, post-60s meltdown) — no more
// moves, no randomness, both browsers compute the same winner; the wager settles concede/agree/refund.
//
// MOVE ENCODING (enc = op + payload·16):
//   op 1 PICK  payload = choice(0..2) + 4·slot(0..5)
//   op 2 SKIP  scrap the whole offer for +12 max HP
import { blake2bHash } from "./nadotx.js";

const H = (v) => BigInt("0x" + blake2bHash(v));

export const ROUNDS = 9, SLOTS = 6, BASE_HP = 350, SHIELD_CAP = 250, MAXRANK = 4;
export const TAGS = ["BLADE", "BOLT", "SPARK", "EMBER", "PLATE", "MEND", "CORE"];

// kind: d=damage s=shield h=heal (burn rides on any weapon) c=core(passive)
// spc: 1 twin-fire · 2 pierces shields · 3 +50% vs burning target · 4 reflect on melee hits ·
//      5 also shields self · (SPARK weapons always deal DOUBLE damage to a shielded target)
export const ITEMS = [
  { k: "shiv", n: "Shiv", tier: 1, tag: 0, cd: 20, kind: "d", b: 20, a: 12, txt: "Quick scrap blade." },
  { k: "scrappistol", n: "Scrap Pistol", tier: 1, tag: 1, cd: 25, kind: "d", b: 26, a: 14, txt: "Bolt-thrower built from plumbing." },
  { k: "blowtorch", n: "Blowtorch", tier: 1, tag: 3, cd: 30, kind: "d", b: 10, a: 6, burn: 2, txt: "Light damage, sets 2 burn." },
  { k: "buckler", n: "Scrap Buckler", tier: 1, tag: 4, cd: 30, kind: "s", b: 26, a: 14, txt: "Raises a small shield." },
  { k: "patchkit", n: "Patch Kit", tier: 1, tag: 5, cd: 45, kind: "h", b: 34, a: 18, txt: "Repairs hull points." },
  { k: "grindstone", n: "Grindstone", tier: 1, tag: 6, kind: "c", b: 10, a: 6, ctag: 0, txt: "All your BLADE items +damage." },
  { k: "powderpack", n: "Powder Pack", tier: 1, tag: 6, kind: "c", b: 10, a: 6, ctag: 1, txt: "All your BOLT items +damage." },
  { k: "ballast", n: "Ballast Slab", tier: 1, tag: 6, kind: "c", b: 60, a: 30, chp: 1, txt: "Raises your max HP." },
  { k: "buzzsaw", n: "Buzz Saw", tier: 2, tag: 0, cd: 35, kind: "d", b: 44, a: 22, txt: "Chews through hulls." },
  { k: "nailrifle", n: "Nail Rifle", tier: 2, tag: 1, cd: 45, kind: "d", b: 56, a: 26, txt: "Heavy nails at range." },
  { k: "arcwelder", n: "Arc Welder", tier: 2, tag: 2, cd: 40, kind: "d", b: 36, a: 18, txt: "SPARK: double damage vs shields." },
  { k: "tarsprayer", n: "Tar Sprayer", tier: 2, tag: 3, cd: 50, kind: "d", b: 0, a: 0, burn: 5, burna: 2, txt: "No damage — heavy burn." },
  { k: "boilerplate", n: "Boiler Plate", tier: 2, tag: 4, cd: 55, kind: "s", b: 56, a: 26, txt: "A slab of shielding." },
  { k: "coolantpump", n: "Coolant Pump", tier: 2, tag: 5, cd: 70, kind: "h", b: 66, a: 30, txt: "Big slow repair." },
  { k: "twinslingers", n: "Twin Slingers", tier: 2, tag: 1, cd: 30, kind: "d", b: 16, a: 8, spc: 1, txt: "Fires twice per trigger." },
  { k: "staticcoil", n: "Static Coil", tier: 2, tag: 2, cd: 55, kind: "d", b: 20, a: 10, spc: 5, sh: 24, sha: 12, txt: "Zaps and shields you." },
  { k: "rivetkit", n: "Rivet Kit", tier: 2, tag: 6, kind: "c", b: 12, a: 6, ctag: 4, txt: "All your PLATE items +shield." },
  { k: "capacitor", n: "Capacitor Bank", tier: 2, tag: 6, kind: "c", b: 12, a: 6, ctag: 2, txt: "All your SPARK items +damage." },
  { k: "accelerant", n: "Accelerant Tank", tier: 2, tag: 6, kind: "c", b: 2, a: 1, cburn: 1, txt: "All your EMBER items +burn." },
  { k: "pipecleaver", n: "Pipe Cleaver", tier: 2, tag: 0, cd: 50, kind: "d", b: 72, a: 34, txt: "Slow, brutal chop." },
  { k: "junkmortar", n: "Junk Mortar", tier: 3, tag: 1, cd: 90, kind: "d", b: 140, a: 60, spc: 2, txt: "Pierces shields entirely." },
  { k: "rebarlance", n: "Rebar Lance", tier: 3, tag: 0, cd: 80, kind: "d", b: 120, a: 55, spc: 3, txt: "+50% damage to a burning target." },
  { k: "teslafist", n: "Tesla Fist", tier: 3, tag: 2, cd: 60, kind: "d", b: 66, a: 30, txt: "SPARK: double damage vs shields." },
  { k: "furnaceheart", n: "Furnace Heart", tier: 3, tag: 3, cd: 70, kind: "d", b: 36, a: 16, burn: 4, burna: 2, txt: "Damage plus 4 burn." },
  { k: "mirrorguard", n: "Mirror Guard", tier: 3, tag: 4, cd: 70, kind: "s", b: 50, a: 24, spc: 4, ref: 8, refa: 4, txt: "Shields; reflects BLADE hits." },
  { k: "welddrone", n: "Weld Drone", tier: 3, tag: 5, cd: 60, kind: "h", b: 36, a: 16, spc: 5, sh: 12, sha: 6, txt: "Repairs and shields a little." },
  { k: "overclock", n: "Overclock Chip", tier: 3, tag: 6, kind: "c", b: 8, a: 4, ccd: 1, txt: "All your cooldowns run faster (%)." },
  { k: "magnetrig", n: "Magnet Rig", tier: 3, tag: 6, kind: "c", b: 4, a: 2, call: 1, txt: "ALL your weapons +damage." },
];

export const encMove = (op, payload) => op + (payload || 0) * 16;
export const decMove = (enc) => ({ op: enc % 16, payload: Math.floor(enc / 16) });
const val = (it, rank) => it.b + it.a * (rank - 1);
export const itemVal = val;

function blockedErr() { const e = new Error("waiting for seed block"); e.blocked = true; return e; }
function log(st, p, ev, x, n) { st.log.push({ p, ev, x, n }); if (st.log.length > 300) st.log.shift(); }
function corrupt(st, why) { st.corrupt = true; st.corruptWhy = why; }

const tiersFor = (r) => (r <= 3 ? [1] : r <= 6 ? [1, 2] : [2, 3]);
// the 3-item offer for player p's round r, derived from the seed q pinned by their previous move
export function deriveOffer(g, p, r, q) {
  if (q == null) return null;
  const ok = tiersFor(r);
  const pool = ITEMS.map((it, i) => (ok.includes(it.tier) ? i : -1)).filter((i) => i >= 0);
  const salt = BigInt(g) * 16777216n + BigInt(p) * 1048576n + BigInt(r) * 4096n;
  return [0, 1, 2].map((i) => pool[Number(H(q + salt + BigInt(i)) % BigInt(pool.length))]);
}
export const offerFor = (st, p) =>
  st.ps[p].round >= ROUNDS ? null : deriveOffer(st.g, p, st.ps[p].round + 1, st.ps[p].pendq);

export function init(g, khQ) {
  return {
    g: Number(g),
    ps: [0, 1].map(() => ({ gear: Array(SLOTS).fill(null), round: 0, maxhp: BASE_HP, pendq: khQ })),
    over: false, result: 0, corrupt: false, corruptWhy: "", log: [], mi: 0,
    blocked: false, blockedAt: -1, combat: null,
  };
}

export function applyMove(st, side, enc) {
  if (st.corrupt) return;
  if (st.over) return corrupt(st, "move after game over");
  const p = side - 1, z = st.ps[p], { op, payload } = decMove(enc);
  if (z.round >= ROUNDS) return corrupt(st, "already drafted " + ROUNDS);
  const offer = offerFor(st, p);
  if (offer == null) throw blockedErr();
  if (op === 1) {
    const choice = payload % 4, slot = Math.floor(payload / 4);
    if (choice > 2 || slot >= SLOTS) return corrupt(st, "pick payload");
    const id = offer[choice], cur = z.gear[slot];
    if (cur && cur.id === id && cur.rank < MAXRANK) {   // merge: same item on the slot — rank up (capped)
      cur.rank++; log(st, p, "merge", id, cur.rank);
    } else if (cur) {
      z.maxhp += 15 + 10 * (cur.rank - 1);
      log(st, p, "scrap", cur.id, cur.rank);
      z.gear[slot] = { id, rank: 1 };
      log(st, p, "pick", id, slot);
    } else {
      z.gear[slot] = { id, rank: 1 };
      log(st, p, "pick", id, slot);
    }
  } else if (op === 2) {
    z.maxhp += 12; log(st, p, "skip");
  } else return corrupt(st, "bad op " + op);
  z.round++;
  z.pendq = st._q === undefined ? null : st._q;   // next offer derives from THIS move's seed
  if (st.ps[0].round >= ROUNDS && st.ps[1].round >= ROUNDS) {
    st.combat = simulate(st);
    st.over = true; st.result = st.combat.result;
    log(st, null, "combat", null, st.result);
  }
}

// ---- deterministic combat ------------------------------------------------------------------------------
// Deciseconds 1..900. Items fire when (t + slot) % cd == 0. Burn: every 10ds take `stacks` damage, then
// stacks-1. Meltdown after 600ds: both take escalating damage every 10ds. SPARK weapons deal DOUBLE to a
// shielded target; spc2 pierces shields; spc3 +50% vs burning; spc4 reflects BLADE hits; spc1 fires twice.
export function buildFighterFrom(z, p) {
  const items = [];
  let maxhp = z.maxhp, cdCut = 0;
  const buf = { tag: [0, 0, 0, 0, 0, 0, 0], all: 0, burn: 0 };
  for (const gitem of z.gear) {
    if (!gitem) continue;
    const it = ITEMS[gitem.id], v = val(it, gitem.rank);
    if (it.kind === "c") {
      if (it.chp) maxhp += v;
      else if (it.ccd) cdCut += v;
      else if (it.call) buf.all += v;
      else if (it.cburn) buf.burn += v;
      else if (it.ctag != null) buf.tag[it.ctag] += v;
    }
  }
  z.gear.forEach((gitem, slot) => {
    if (!gitem) return;
    const it = ITEMS[gitem.id];
    if (it.kind === "c") return;
    const v = val(it, gitem.rank) + buf.tag[it.tag] + (it.kind === "d" ? buf.all : 0);
    const cd = Math.max(10, Math.round(it.cd * (100 - Math.min(40, cdCut)) / 100));
    items.push({ id: gitem.id, rank: gitem.rank, slot, cd, kind: it.kind, v,
      burn: it.burn ? it.burn + (it.burna || 0) * (gitem.rank - 1) + buf.burn : 0,
      sh: it.sh ? it.sh + (it.sha || 0) * (gitem.rank - 1) : 0,
      ref: it.ref ? it.ref + (it.refa || 0) * (gitem.rank - 1) : 0,
      spc: it.spc || 0, tag: it.tag });
  });
  return { p, maxhp, hp: maxhp, shield: 0, burn: 0, items,
    reflect: items.reduce((m, i) => m + (i.spc === 4 ? i.ref : 0), 0) };
}
export function simulate(st) { return simulateBuilds(st.ps[0], st.ps[1]); }
// simulateBuilds(z0, z1): fight two raw builds ({gear, maxhp}) — the PvP settle AND the solo gauntlet.
export function simulateBuilds(z0, z1) {
  const F = [buildFighterFrom(z0, 0), buildFighterFrom(z1, 1)];
  const ev = [];
  const push = (t, p, e, x, n) => { if (ev.length < 900) ev.push({ t, p, e, x, n }); };
  const hit = (t, from, to, item, amount) => {
    let dmg = amount;
    if (item.spc === 3 && to.burn > 0) dmg = Math.floor(dmg * 3 / 2);
    if (item.tag === 2 && to.shield > 0) dmg *= 2;
    if (item.spc === 2) { to.hp -= dmg; }
    else {
      const absorbed = Math.min(to.shield, dmg);
      to.shield -= absorbed; to.hp -= dmg - absorbed;
    }
    if (item.tag === 0 && to.reflect > 0) from.hp -= to.reflect;
    push(t, from.p, "hit", item.id, dmg);
  };
  let result = 0;
  for (let t = 1; t <= 900 && !result; t++) {
    if (t % 10 === 0) {
      for (const f of F) if (f.burn > 0) { f.hp -= f.burn; push(t, f.p, "burn", null, f.burn); f.burn--; }
      if (t > 600) { const m = Math.floor((t - 600) / 50) + 1; for (const f of F) f.hp -= m; }
    }
    for (let slot = 0; slot < SLOTS; slot++) for (const f of F) {
      const o = F[1 - f.p];
      for (const item of f.items) {
        if (item.slot !== slot || (t + slot) % item.cd !== 0) continue;
        if (item.kind === "d") {
          const times = item.spc === 1 ? 2 : 1;
          for (let i = 0; i < times; i++) if (item.v > 0) hit(t, f, o, item, item.v);
          if (item.burn) { o.burn += item.burn; push(t, f.p, "ignite", item.id, item.burn); }
          if (item.spc === 5 && item.sh) f.shield = Math.min(SHIELD_CAP, f.shield + item.sh);
        } else if (item.kind === "s") {
          f.shield = Math.min(SHIELD_CAP, f.shield + item.v);
          push(t, f.p, "shield", item.id, item.v);
        } else if (item.kind === "h") {
          const healed = Math.min(f.maxhp - f.hp, item.v);
          if (healed > 0) push(t, f.p, "heal", item.id, healed);
          f.hp += healed;
          if (item.spc === 5 && item.sh) f.shield = Math.min(SHIELD_CAP, f.shield + item.sh);
        }
      }
    }
    const k0 = F[0].hp <= 0, k1 = F[1].hp <= 0;
    if (k0 || k1) result = k0 && k1 ? 3 : k0 ? 2 : 1;
  }
  if (!result) {
    const r0 = F[0].hp * 1000 / F[0].maxhp, r1 = F[1].hp * 1000 / F[1].maxhp;
    result = r0 === r1 ? 3 : r0 > r1 ? 1 : 2;
  }
  return { result, hp: [Math.max(0, F[0].hp), Math.max(0, F[1].hp)], maxhp: [F[0].maxhp, F[1].maxhp], ev };
}

// ---- SOLO GAUNTLET -------------------------------------------------------------------------------------
// The free single-player roguelike mode: endless stages vs procedurally generated enemy builds, run
// entirely client-side (no stake, no chain — staked play stays PvP: a house-banked SKILL game would let
// any decent drafter drain the bank). Deterministic from a seed string, so a shared "daily" seed gives
// everyone the same gauntlet to race on. Loop per attempt: draw an offer (seeded by the attempt counter,
// so a lost fight still changes your options) → pick / merge / scrap / skip → fight the current stage.
// Win → next stage. Lose → lose a life; out of lives → run over, score = stages cleared.
export const SOLO_LIVES = 2, PICKS_PER_FIGHT = 2, GRIT_HP = 25;
const SOLO_SALT = 777216n;                               // keeps solo streams disjoint from PvP offers
export const soloQ = (seed) => H("scrapline-solo:" + seed);

// offer tiers key off the STAGE you're fighting, so counters unlock when the enemies escalate.
export function soloOffer(seed, offerN, stage) {
  const q = soloQ(seed);
  const ok = stage <= 2 ? [1] : stage <= 5 ? [1, 2] : [2, 3];
  const pool = ITEMS.map((it, i) => (ok.includes(it.tier) ? i : -1)).filter((i) => i >= 0);
  const salt = SOLO_SALT + BigInt(offerN) * 4096n;
  return [0, 1, 2].map((i) => pool[Number(H(q + salt + BigInt(i)) % BigInt(pool.length))]);
}
// the stage-s enemy: item count, ranks and hull all escalate — unbounded, so every run ends eventually.
export function enemyBuild(seed, stage) {
  const q = soloQ(seed);
  const salt = SOLO_SALT + 1n + BigInt(stage) * 65536n;
  const ok = stage <= 2 ? [1] : stage <= 5 ? [1, 2] : [1, 2, 3];
  const pool = ITEMS.map((it, i) => (ok.includes(it.tier) ? i : -1)).filter((i) => i >= 0);
  const n = Math.min(SLOTS, 2 + Math.floor((stage - 1) / 2));
  const rank = Math.min(MAXRANK, 1 + Math.floor(stage / 4));
  const gear = Array(SLOTS).fill(null);
  for (let i = 0; i < n; i++) {
    let id = pool[Number(H(q + salt + BigInt(i)) % BigInt(pool.length))];
    if (i === 0) { // guarantee a weapon so stage 1 can't be a pacifist stall
      const dPool = pool.filter((x) => ITEMS[x].kind === "d");
      id = dPool[Number(H(q + salt + BigInt(i)) % BigInt(dPool.length))];
    }
    const bump = stage >= 4 ? Number(H(q + salt + 100n + BigInt(i)) % 2n) : 0;
    gear[i] = { id, rank: Math.min(MAXRANK, rank + bump) };
  }
  return { gear, maxhp: 220 + 60 * (stage - 1) };
}
export function soloNew(seed) {
  const gear = Array(SLOTS).fill(null);
  gear[0] = { id: 0, rank: 1 };                          // every wreck starts with a Shiv
  return { seed: String(seed), stage: 1, lives: SOLO_LIVES, offerN: 0, choices: [],
    gear, maxhp: BASE_HP, over: false, score: 0, lastCombat: null, picks: PICKS_PER_FIGHT };
}
export const soloOfferFor = (run) => (run.over || run.picks <= 0 ? null : soloOffer(run.seed, run.offerN, run.stage));
// choice: 0..2 into a slot, or -1 = scrap the offer (+12 max HP). Mirrors the PvP pick/merge/replace
// rules. TWO offers precede every fight (the salvage economy that makes the curve climbable). Every
// attempt is RECORDED (5 bits: c + 4·slot, c=3 for scrap) — the run's choice list IS the whole run, so
// a daily score claim = (day, choices) and anyone can verify it by replaying.
export function soloPick(run, choice, slot) {
  if (run.over || run.picks <= 0) return false;
  if (choice === -1) { run.maxhp += 12; run.offerN++; run.picks--; run.choices.push(3); return true; }
  const offer = soloOffer(run.seed, run.offerN, run.stage);
  if (choice > 2 || slot >= SLOTS) return false;
  const id = offer[choice], cur = run.gear[slot];
  if (cur && cur.id === id && cur.rank < MAXRANK) cur.rank++;
  else {
    if (cur) run.maxhp += 15 + 10 * (cur.rank - 1);
    run.gear[slot] = { id, rank: 1 };
  }
  run.offerN++; run.picks--; run.choices.push(choice + 4 * slot);
  return true;
}
// ---- daily highscore claims (packing + client-side verification) ----------------------------------------
// packChoices: 10 five-bit attempts per word (words < 2^50 — safe through JSON number decoding), 8 words
// max = 80 attempts (two picks per fight doubles the choice count of a deep run). The contract stores
// claims blindly; every browser verifies by REPLAYING the run and silently drops claims that don't
// reproduce (posting costs a tx fee, which caps spam).
export const ATT_PER_WORD = 10, MAX_WORDS = 8, MAX_ATT = ATT_PER_WORD * MAX_WORDS;
export function packChoices(choices) {
  const words = [];
  for (let w = 0; w < MAX_WORDS; w++) {
    let v = 0n;
    for (let i = ATT_PER_WORD - 1; i >= 0; i--) v = v * 32n + BigInt(choices[w * ATT_PER_WORD + i] || 0);
    words.push(v);
  }
  return words;
}
export function unpackChoices(words, n) {
  const out = [];
  for (let w = 0; w < MAX_WORDS && out.length < n; w++) {
    let v = BigInt(words[w] || 0);
    for (let i = 0; i < ATT_PER_WORD && out.length < n; i++) { out.push(Number(v % 32n)); v /= 32n; }
  }
  return out;
}
export const seedOfDay = (day) => "daily-" + new Date(day * 86400000).toISOString().slice(0, 10);
// verifyClaim: replay a posted (day, n, words) claim; returns the true score, or -1 if the claim is bogus.
export function verifyClaim(day, n, words) {
  if (!(n > 0 && n <= MAX_ATT)) return -1;
  const atts = unpackChoices(words, n);
  const run = soloNew(seedOfDay(day));
  for (const att of atts) {
    if (run.over) return -1;                             // trailing choices past death
    const c = att % 4, slot = Math.floor(att / 4);
    if (slot >= SLOTS) return -1;
    if (!soloPick(run, c === 3 ? -1 : c, slot)) return -1;
    soloFight(run);
  }
  return run.over ? run.score : -1;                      // only finished runs count
}
export function soloFight(run) {
  if (run.over || run.picks > 0) return null;
  const enemy = enemyBuild(run.seed, run.stage);
  const c = simulateBuilds({ gear: run.gear, maxhp: run.maxhp }, enemy);
  run.lastCombat = { ...c, stage: run.stage, enemy };
  run.picks = PICKS_PER_FIGHT;                            // fresh salvage precedes the next fight either way
  if (c.result === 1 || c.result === 3) { run.score = run.stage; run.stage++; }
  else { run.lives--; run.maxhp += GRIT_HP; if (run.lives < 0) run.over = true; }   // grit: retries hit harder
  return run.lastCombat;
}

// ---- replay --------------------------------------------------------------------------------------------
export function replay(g, khQ, recs) {
  if (khQ == null && recs.length === 0) return { blocked: true, blockedAt: -1, setup: true };
  let st = init(g, khQ);
  for (let i = 0; i < recs.length; i++) {
    const snap = structuredClone(st);
    st._q = recs[i].q;
    try { applyMove(st, recs[i].side, recs[i].enc); st.mi = i + 1; }
    catch (e) {
      if (!e.blocked) throw e;
      st = snap; st.blocked = true; st.blockedAt = i;
      break;
    }
    if (st.corrupt) break;
  }
  delete st._q;
  return st;
}
