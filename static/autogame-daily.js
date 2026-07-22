// autogame-daily.js — the FREE DAILY GAUNTLET: Autogame's rules with the chain pacing taken out, so the
// whole march fits in one sitting and can be ranked on a leaderboard nobody can forge
// (doc/provable-practice.md + static/provable.js).
//
// The staked march is paced by the chain — one leg per LEG blocks, for as long as you care to walk — and
// that pacing is the point of it. It is also exactly why it can never BE a daily board: a board wants
// everyone walking the same road on the same day. The Gauntlet is that road: 124 fixed steps derived from
// the day's on-chain anchor and YOUR address, played at your own speed, free, then posted as a claim that
// every verifier replays.
//
// NOT A SECOND RULEBOOK. Every step goes through autogame-engine.js's `step` — the same function the
// animator uses and the same one tests/autogame_contract_test.py proves equal to the contract, step for
// step. This file adds only two things: where the world comes from (the seed instead of two block hashes)
// and how a run is packed into a claim. If it ever starts making rules of its own, it is wrong.
//
// WHY AUTOGAME QUALIFIES for a provable board at all. provable.js's soundness rule is that the seed is
// necessarily known at play time, so a game whose optimal play falls straight out of the RNG stream turns
// its board into a solver race. Autogame does not: the road is visible, but picking 124 reactions to
// maximise a compounding renown/gear/streak/stamina economy — with a cash-out decision live at every step
// — is a planning problem with branching factor 8 and a horizon of 124. Knowing the road is the premise of
// the puzzle, not the answer to it.
import { algHashn } from "./nadodapp.js?v=4984604e";
import { H, provableSeed, unpackMoves, packMoves } from "./provable.js?v=a13bb487";
import * as R from "./autogame-rules.js?v=e7abffe6";
import * as E from "./autogame-engine.js?v=eb6129b3";

export const SLUG = "autogame";
export const ACT_BITS = 3;            // an action is 0..7 (A_DEFAULT..A_RALLY) — 16 symbols per field word
export const WORDS = 8;               // 8 x 16 = 128 symbols in a claim
export const HEAD = 4;                // ...the first four are the loadout
export const STEPS = 128 - HEAD;      // ...leaving 124 steps of road
export const RUN_ID = 0;              // the world derivation's "run id" slot; the seed already binds day+addr

// ── the loadout, packed into the first four symbols ──────────────────────────────────────────────
// The march lets you dial stance, aggression, weapon/armour focus and the auto-drink threshold freely.
// A 3-bit symbol cannot carry 0..100, so the Gauntlet offers eight rungs of each — enough that the builds
// stay genuinely distinct (the thing the whole design is for) without a second encoding.
export const AGG_OF = (t) => t * 2 + 1;              // 1,3,5 … 15   (AGG_MAX is 16)
export const PCT_OF = (t) => t * 14;                 // 0,14,28 … 98
export const TIERS = 8;

export function loadoutOf(syms) {
  return { stance: syms[0], agg: AGG_OF(syms[1]), focus: PCT_OF(syms[2]), healpct: PCT_OF(syms[3]) };
}
export function packClaim(loadTiers, actions) {
  return packMoves(loadTiers.concat(actions), ACT_BITS);
}

// ── the day's road ───────────────────────────────────────────────────────────────────────────────
// On chain a leg's terrain comes from BHASH(lh) and its dice from BHASH(nh), and the step index is folded
// in by autogame-engine's `words`. Here the two hashes come from the seed instead — everything downstream
// is byte-identical to the live game, which is the only reason a Gauntlet run looks and feels like a march.
export function dailyWorld(seed) {
  const s = BigInt("0x" + String(H(seed)).slice(0, 32));   // algHashn folds it into the field itself
  return { tileHash: algHashn([s, 1n]), rollHash: algHashn([s, 2n]) };
}
/** The (tileWord, rollWord) pair for step `i` — the same shape the chain hands a leg. */
export function wordsAt(world, i) {
  return { tw: E.words(algHashn, world.tileHash, RUN_ID, i), rw: E.words(algHashn, world.rollHash, RUN_ID, i) };
}
/** The road ahead, in exactly the shape the march's road strip and the animator already consume — this is
 *  autogame-engine's own peekLeg, pointed at an absolute step instead of a leg boundary. The Gauntlet gets
 *  the same tile names, monster levels and swing numbers as the staked game because it is the same call. */
export function roadAhead(world, run, from, n) {
  return E.peekLeg(algHashn, run, RUN_ID, world.tileHash, from, Math.min(n, Math.max(0, STEPS - from)));
}

// ── playing a Gauntlet ───────────────────────────────────────────────────────────────────────────
/**
 * play(seed, loadTiers, actions) -> { run, events, score }
 * Walks `actions.length` steps (capped at STEPS) and then, if still standing, RETIRES — which is what
 * makes stopping early a real decision rather than a forfeit: the road bonus is pro-rata on depth, so
 * every extra step raises the payout and dying loses three quarters of what is unbanked. Play deep or
 * take the money; the board ranks whichever you chose better.
 */
export function play(seed, loadTiers, actions, open = false) {
  const ld = loadoutOf(loadTiers);
  const world = dailyWorld(seed);
  const run = E.newRun({ stance: ld.stance, healpct: ld.healpct, focus: ld.focus });
  run.agg = ld.agg;
  const events = [];
  const n = Math.min(actions.length, STEPS);
  for (let i = 0; i < n; i++) {
    if (!run.alive || run.done) break;
    const { tw, rw } = wordsAt(world, i);
    events.push(E.step(run, tw, rw, ld.agg, ld.stance, ld.focus, ld.healpct, actions[i]));
  }
  // `open` is the UI's replay-in-progress: the run is mid-walk and must NOT be marked retired, or every
  // panel that asks "is this run live?" reads a walker as a quitter. A CLAIM is never open — the posted
  // run is finished by definition, and retiring the standing survivor is what scores it.
  if (!open && run.alive && !run.done) run.retired = 1;
  return { run, events, score: E.score(run) };
}


/** The score IF YOU STOPPED RIGHT NOW — an open run valued under the claim rule (retire on your feet). */
export function scoreIfStopped(run) {
  if (!run.alive || run.done || run.retired) return E.score(run);
  const c = { ...run, mats: [...run.mats], gear: [...run.gear], retired: 1 };
  return E.score(c);
}

/**
 * verifyClaim(day, n, words, anchorHash, addr) -> the TRUE score, or -1 if the claim is malformed.
 * The faucet oracle and every browser keep a claim only when this equals the POSTED score, so neither a
 * fabricated score nor a copied move list can rank (the seed binds the poster's own address).
 */
export function verifyClaim(day, n, words, anchorHash, addr) {
  n = Number(n);
  if (!(n > HEAD) || n > HEAD + STEPS) return -1;
  const syms = unpackMoves(words, ACT_BITS, n);
  if (syms.some((v) => v < 0 || v > 7)) return -1;
  const tiers = syms.slice(0, HEAD);
  if (tiers[0] >= R.STANCES.length) return -1;                       // only four stances exist
  if (tiers.slice(1).some((v) => v >= TIERS)) return -1;
  return play(provableSeed(SLUG, day, anchorHash, addr), tiers, syms.slice(HEAD)).score;
}
