// Differential check: the browser engine (static/autogame-engine.js) against the Python reference model.
//
// Usage:  node tests/autogame_engine_verify.mjs <vectors.json>
//
// The vectors are produced by tests/autogame_contract_test.py, which has already proven the Python model
// agrees with the contract step for step. Chaining the two makes the browser engine transitively verified
// against the chain — which matters because the client uses it to preview a plan and to animate a leg, and
// a preview that disagrees with the settlement is worse than no preview at all.
//
// The vectors carry the raw 32-bit hash windows rather than block hashes, so this runs without any crypto:
// what is under test is the STEP FUNCTION, not the sponge (nadodapp's alghash port is verified separately).
import { readFileSync } from "node:fs";
import * as E from "../static/autogame-engine.js";

const path = process.argv[2];
if (!path) {
  console.error("usage: node tests/autogame_engine_verify.mjs <vectors.json>");
  process.exit(2);
}
const cases = JSON.parse(readFileSync(path, "utf8"));

const FIELDS = ["hp", "maxhp", "stam", "potions", "xp", "banked", "streak", "depth", "kills",
                "alive", "done", "wlevel", "alevel"];

let checked = 0;
for (const c of cases) {
  const run = E.newRun({ stance: c.stance, healpct: c.healpct, focus: c.focus });
  run.doctrine = c.doctrine;
  run.agg = c.agg;
  for (let n = 0; n < c.steps.length; n++) {
    const s = c.steps[n];
    E.step(run, s.tw, s.rw, s.doctrine, s.agg);
    const want = s.after;
    for (const f of FIELDS) {
      if (run[f] !== want[f]) {
        console.error(`case ${c.name} step ${n}: ${f} = ${run[f]}, python model says ${want[f]}`);
        console.error(`  inputs: tw=${s.tw} rw=${s.rw} agg=${s.agg} doctrine=[${s.doctrine}]`);
        process.exit(1);
      }
    }
    for (let g = 0; g < run.gear.length; g++) {
      if (run.gear[g] !== want.gear[g]) {
        console.error(`case ${c.name} step ${n}: gear[${g}] = ${run.gear[g]}, python says ${want.gear[g]}`);
        process.exit(1);
      }
    }
    for (let m = 0; m < run.mats.length; m++) {
      if (run.mats[m] !== want.mats[m]) {
        console.error(`case ${c.name} step ${n}: mats[${m}] = ${run.mats[m]}, python says ${want.mats[m]}`);
        process.exit(1);
      }
    }
    checked++;
    if (!run.alive || run.done) break;
  }

  if (c.score !== undefined && E.score(run) !== c.score) {
    console.error(`case ${c.name}: score = ${E.score(run)}, python says ${c.score}`);
    process.exit(1);
  }
}
console.log(`OK ${cases.length} cases, ${checked} steps`);
