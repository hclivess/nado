/*
 * autogame_daily_play.mjs — plays ONE complete Daily Gauntlet honestly and prints the postable claim as a
 * single JSON line: {score, n, words, depth, alive, ok}. `ok` is a local verifyClaim round-trip, so a claim
 * that would not survive the oracle never even leaves this script.
 *
 * The player is a one-ply greedy: at each step it tries every action the DERIVED action matrix offers for
 * that tile and keeps the one whose resulting run is worth most if you stopped right there. That is a real
 * player's reasoning, not an oracle — it does not look ahead, and it does not know the road. It exists so
 * the live E2E posts a score that a human could actually have reached, rather than a hand-written constant.
 *
 * IT READS THE ANCHOR ITSELF, out of the contract view, exactly as every other verifier does — it is not
 * passed in. The reason is a precision trap worth knowing about: an anchor is a field element up to 2^64,
 * JSON has no integers, and so `JSON.parse` in ANY JavaScript engine rounds it to the nearest double.
 * 4823474900883014428 comes back as 4823474900883015000. Every verifier is JavaScript, so they all round
 * identically and the board is perfectly self-consistent — but a caller that read the same number in Python
 * and handed the exact string in would seed a DIFFERENT run and its claim would never verify. The anchor is
 * defined as what the verifiers read, so the verifiers are what read it.
 *
 * Usage: node tests/autogame_daily_play.mjs <cid> <utcDay> <addr> [execUrl]
 */
import { provableSeed, anchorOf } from "../static/provable.js";
import * as R from "../static/autogame-rules.js";
import * as E from "../static/autogame-engine.js";
import * as D from "../static/autogame-daily.js";

const [cid, dayArg, addr, execArg] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const day = Number(dayArg);
const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const anchor = anchorOf(sto, (s, n) => s[n] || {}, day);
if (!anchor) { console.log(JSON.stringify({ error: "day not anchored" })); process.exit(1); }
const seed = provableSeed(D.SLUG, day, anchor, addr);
const clone = (r) => ({ ...r, mats: [...r.mats], gear: [...r.gear] });

// A middling build: balanced stance, a real but not reckless pull, weapon-leaning, drink at 42%.
const TIERS = [0, 2, 4, 3];
const ld = D.loadoutOf(TIERS);
const world = D.dailyWorld(seed);

let run = E.newRun({ stance: ld.stance, healpct: ld.healpct, focus: ld.focus });
run.agg = ld.agg;
const actions = [];
for (let i = 0; i < D.STEPS; i++) {
  if (!run.alive || run.done) break;
  const tile = D.roadAhead(world, run, i, 1)[0];
  const { tw, rw } = D.wordsAt(world, i);
  let best = null;
  for (const a of (R.ACTS_FOR[tile.tile] || [0])) {
    const cand = clone(run);
    E.step(cand, tw, rw, ld.agg, ld.stance, ld.focus, ld.healpct, a);
    // value it as if you stopped here: renown you would walk away with, plus a small premium on staying
    // alive, because a dead run cannot take another step
    const asIf = clone(cand);
    if (asIf.alive && !asIf.done) asIf.retired = 1;
    const v = E.score(asIf) + (cand.alive ? cand.hp * 3 + cand.stam * 5 : 0);
    if (!best || v > best.v) best = { v, a, cand };
  }
  actions.push(best.a);
  run = best.cand;
}

const alive = !!run.alive;
if (run.alive && !run.done) run.retired = 1;
const score = E.score(run);
const words = D.packClaim(TIERS, actions);
const n = D.HEAD + actions.length;
const ok = D.verifyClaim(day, n, words, anchor, addr) === score;
console.log(JSON.stringify({ score, n, words, depth: run.depth, alive, ok, anchor }));
